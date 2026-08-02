"""Rule-based detection tests.

The exemption tests are the ones that matter most. The first real run of these
detectors produced 143 findings on this project's own source, of which 82 were
exception subclasses and enums flagged as Lazy Class or Data Class -- classes
that are *supposed* to look that way. Precision, not recall, is what makes a
rule baseline usable, and these tests pin it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codesmell.config.settings import IngestionSettings
from codesmell.core.enums import EntityType, Severity, SmellType, SourceKind
from codesmell.core.models import CodeEntity, EntityFacts, FeatureVector, Language
from codesmell.detectors import (
    Combinator,
    Condition,
    DetectionEngine,
    Operator,
    RuleBasedDetector,
    RuleConfigError,
    SmellRule,
    ThresholdMode,
    ThresholdTable,
    load_rules,
    percentile,
)
from codesmell.detectors.rules import Exemption
from codesmell.detectors.thresholds import MIN_ENTITIES_FOR_PERCENTILES
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.languages.python import PythonParser
from codesmell.metrics import DEFAULT_CALCULATORS, MetricsEngine
from codesmell.metrics.engine import FeatureSchema


@pytest.fixture
def schema() -> FeatureSchema:
    return FeatureSchema.from_calculators(DEFAULT_CALCULATORS)


@pytest.fixture
def engine() -> MetricsEngine:
    return MetricsEngine(
        parsers={Language.PYTHON: PythonParser()}, calculators=DEFAULT_CALCULATORS
    )


def _analyze(engine: MetricsEngine, root: Path, files: dict[str, str]):
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    inventory = ProjectInventoryBuilder(IngestionSettings()).build(
        root, name="fixture", source_kind=SourceKind.DIRECTORY
    )
    return engine.analyze(root, inventory)


def _entity(
    name: str = "Thing", entity_type: EntityType = EntityType.CLASS
) -> CodeEntity:
    return CodeEntity(
        entity_id=f"m.py::{name}",
        entity_type=entity_type,
        name=name,
        qualified_name=f"m.{name}",
        relative_path="m.py",
        start_line=1,
        end_line=10,
        language=Language.PYTHON,
    )


def _vector(entity: CodeEntity, **values: float) -> FeatureVector:
    return FeatureVector(
        entity_id=entity.entity_id, entity_type=entity.entity_type, values=values
    )


# --------------------------------------------------------------------- #
# Conditions and severity
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("operator", "value", "threshold", "expected"),
    [
        (Operator.GT, 11.0, 10.0, True),
        (Operator.GT, 10.0, 10.0, False),
        (Operator.GTE, 10.0, 10.0, True),
        (Operator.LT, 9.0, 10.0, True),
        (Operator.LTE, 10.0, 10.0, True),
        (Operator.LT, 10.0, 10.0, False),
    ],
)
def test_operator_semantics(operator, value, threshold, expected):
    assert operator.holds(value, threshold) is expected


def test_excess_grows_with_distance_past_a_lower_bound():
    condition = Condition("wmc", Operator.GT, absolute=10.0)
    assert condition.excess(10.0, 10.0) == pytest.approx(1.0)
    assert condition.excess(40.0, 10.0) == pytest.approx(4.0)


def test_excess_inverts_for_upper_bound_conditions():
    """`loc < 25` at loc=5 is five times further into the smelly direction.

    Without the inversion, "further past the threshold" would mean a smaller
    number for half the rules and severity would be meaningless.
    """
    condition = Condition("loc", Operator.LT, absolute=25.0)
    assert condition.excess(25.0, 25.0) == pytest.approx(1.0)
    assert condition.excess(5.0, 25.0) == pytest.approx(5.0)


def test_excess_survives_a_zero_threshold():
    """`lcom_hs > 0` is a legitimate rule and must not divide by zero."""
    condition = Condition("lcom_hs", Operator.GT, absolute=0.0)
    assert condition.excess(0.5, 0.0) == pytest.approx(1.5)


def test_excess_of_a_zero_value_against_an_upper_bound_is_infinite():
    condition = Condition("wmc", Operator.LTE, absolute=3.0)
    assert condition.excess(0.0, 3.0) == float("inf")


@pytest.mark.parametrize(
    ("excess", "expected"),
    [
        (1.0, Severity.LOW),
        (1.4, Severity.LOW),
        (1.5, Severity.MEDIUM),
        (2.4, Severity.MEDIUM),
        (2.5, Severity.HIGH),
        (4.0, Severity.CRITICAL),
        (99.0, Severity.CRITICAL),
    ],
)
def test_severity_bands(excess, expected):
    rule = SmellRule(
        smell_type=SmellType.LARGE_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(Condition("loc", Operator.GT, 200.0),),
    )
    assert rule.severity_for(excess) is expected


def test_rule_rejects_an_entity_type_contradicting_the_smell():
    """SmellType already declares its unit of analysis; a rule may not disagree,
    or a class-level rule would be evaluated against method feature vectors."""
    with pytest.raises(RuleConfigError, match="contradicts"):
        SmellRule(
            smell_type=SmellType.GOD_CLASS,
            entity_type=EntityType.METHOD,
            conditions=(Condition("wmc", Operator.GT, 47.0),),
        )


def test_rule_rejects_an_empty_condition_list():
    with pytest.raises(RuleConfigError, match="no conditions"):
        SmellRule(
            smell_type=SmellType.GOD_CLASS,
            entity_type=EntityType.CLASS,
            conditions=(),
        )


def test_condition_rejects_an_out_of_range_percentile():
    with pytest.raises(RuleConfigError, match="percentile"):
        Condition("wmc", Operator.GT, 47.0, percentile=150.0)


# --------------------------------------------------------------------- #
# Exemptions
# --------------------------------------------------------------------- #


def test_exemption_matches_a_base_class():
    exemption = Exemption(base_class_patterns=(".*Error",))
    facts = EntityFacts(base_names=("ValueError",))
    assert exemption.reason(_entity(), facts) == "inherits from ValueError"


def test_exemption_matches_a_decorator():
    exemption = Exemption(decorator_patterns=("dataclass",))
    facts = EntityFacts(decorators=("dataclass",))
    assert exemption.reason(_entity(), facts) == "decorated with @dataclass"


def test_exemption_matches_a_name():
    exemption = Exemption(name_patterns=(".*Protocol",))
    assert exemption.reason(_entity("ParserProtocol"), EntityFacts()) is not None


def test_exemption_patterns_are_full_match_not_substring():
    """`Enum` must not exempt `EnumeratedThing`."""
    exemption = Exemption(base_class_patterns=("Enum",))
    assert exemption.reason(_entity(), EntityFacts(base_names=("EnumLike",))) is None
    assert exemption.reason(_entity(), EntityFacts(base_names=("Enum",))) is not None


def test_exemption_rejects_an_invalid_regex():
    exemption = Exemption(base_class_patterns=("[unclosed",))
    with pytest.raises(RuleConfigError, match="invalid exemption pattern"):
        exemption.reason(_entity(), EntityFacts(base_names=("X",)))


def test_unexempted_entity_is_not_exempt():
    exemption = Exemption(base_class_patterns=("Enum",))
    assert exemption.reason(_entity(), EntityFacts(base_names=("Base",))) is None


# --------------------------------------------------------------------- #
# Rule file loading
# --------------------------------------------------------------------- #


def test_bundled_rules_validate_against_the_live_schema(schema: FeatureSchema):
    """Guards against a metric being renamed and a rule silently never firing."""
    rules = load_rules(schema=schema)
    assert len(rules) >= 10
    for rule in rules:
        available = set(schema.names_for(rule.entity_type))
        for condition in rule.conditions:
            assert condition.metric in available


def test_every_bundled_rule_carries_a_rationale_and_references():
    """A detector that cannot say why it fired is useless as a baseline and
    useless in a UI whose whole promise is explanation."""
    for rule in load_rules():
        assert rule.rationale, f"{rule.smell_type.value} has no rationale"
        assert rule.references, f"{rule.smell_type.value} has no references"


def test_load_rejects_an_unknown_metric(tmp_path: Path, schema: FeatureSchema):
    """A typo'd metric would make the rule never fire and report a clean
    project -- the worst possible failure mode. It must fail at load time."""
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nsmells:\n"
        "  god_class:\n    entity_type: class\n"
        "    conditions:\n      - metric: lcom\n        op: '>'\n"
        "        absolute: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleConfigError, match="feature schema does not define"):
        load_rules(path, schema=schema)


def test_load_accepts_an_unknown_metric_without_a_schema(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nsmells:\n"
        "  god_class:\n    entity_type: class\n"
        "    conditions:\n      - metric: anything\n        op: '>'\n"
        "        absolute: 1\n",
        encoding="utf-8",
    )
    assert len(load_rules(path)) == 1


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("version: 2\nsmells: {}\n", "unsupported rule file version"),
        ("version: 1\n", "declares no smells"),
        ("just a string\n", "must be a mapping"),
        (
            "version: 1\nsmells:\n  not_a_real_smell:\n    entity_type: class\n"
            "    conditions:\n      - metric: loc\n        op: '>'\n"
            "        absolute: 1\n",
            "unknown smell name",
        ),
        (
            "version: 1\nsmells:\n  god_class:\n    entity_type: class\n"
            "    conditions:\n      - metric: loc\n        op: '~'\n"
            "        absolute: 1\n",
            "unknown operator",
        ),
        (
            "version: 1\nsmells:\n  god_class:\n    entity_type: class\n"
            "    conditions:\n      - metric: loc\n        op: '>'\n",
            "missing an absolute threshold",
        ),
        (
            "version: 1\nsmells:\n  god_class:\n    entity_type: class\n"
            "    conditions: []\n",
            "no conditions",
        ),
        (
            "version: 1\nsmells:\n  god_class:\n    entity_type: widget\n"
            "    conditions:\n      - metric: loc\n        op: '>'\n"
            "        absolute: 1\n",
            "unknown entity_type",
        ),
    ],
)
def test_malformed_rule_files_are_rejected(tmp_path: Path, body: str, match: str):
    path = tmp_path / "rules.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(RuleConfigError, match=match):
        load_rules(path)


def test_load_rejects_invalid_yaml(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text("version: 1\nsmells:\n  - [unclosed\n", encoding="utf-8")
    with pytest.raises(RuleConfigError, match="not valid YAML"):
        load_rules(path)


def test_load_rejects_a_missing_file(tmp_path: Path):
    with pytest.raises(RuleConfigError, match="could not be read"):
        load_rules(tmp_path / "nope.yaml")


def test_shared_exemption_sets_are_reusable(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\n"
        "exemption_sets:\n"
        "  errors:\n    base_class_matches: ['.*Error']\n"
        "smells:\n"
        "  lazy_class:\n    entity_type: class\n"
        "    exempt_if:\n      use: [errors]\n"
        "    conditions:\n      - metric: loc\n        op: '<'\n"
        "        absolute: 25\n",
        encoding="utf-8",
    )
    rule = load_rules(path)[0]
    assert rule.exempts(_entity(), EntityFacts(base_names=("ValueError",)))


def test_load_rejects_an_undefined_exemption_reference(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nsmells:\n  lazy_class:\n    entity_type: class\n"
        "    exempt_if:\n      use: [does_not_exist]\n"
        "    conditions:\n      - metric: loc\n        op: '<'\n"
        "        absolute: 25\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleConfigError, match="undefined exemption set"):
        load_rules(path)


# --------------------------------------------------------------------- #
# Percentile thresholds
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("q", "expected"),
    [(0.0, 1.0), (50.0, 3.0), (100.0, 5.0), (25.0, 2.0), (75.0, 4.0)],
)
def test_percentile_interpolation(q, expected):
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], q) == pytest.approx(expected)


def test_percentile_of_empty_and_single_samples():
    assert percentile([], 90.0) == 0.0
    assert percentile([7.0], 90.0) == 7.0


def test_threshold_table_refuses_percentiles_on_a_small_sample():
    """The 90th percentile of six values is the second-largest value, which
    flags something no matter how healthy the code is."""
    entity = _entity()
    table = ThresholdTable.from_vectors(
        [_vector(entity, wmc=float(i)) for i in range(5)]
    )
    assert table.percentile(EntityType.CLASS, "wmc", 90.0) is None


def test_threshold_table_answers_once_the_sample_is_large_enough():
    entity = _entity()
    table = ThresholdTable.from_vectors(
        [
            _vector(entity, wmc=float(i))
            for i in range(MIN_ENTITIES_FOR_PERCENTILES + 5)
        ]
    )
    assert table.percentile(EntityType.CLASS, "wmc", 50.0) is not None


def test_threshold_table_reports_unknown_metrics_as_unsupported():
    table = ThresholdTable.from_vectors([_vector(_entity(), wmc=1.0)])
    assert table.percentile(EntityType.CLASS, "not_a_metric", 90.0) is None


# --------------------------------------------------------------------- #
# Detector behaviour
# --------------------------------------------------------------------- #


def _detector(
    rule: SmellRule, mode: ThresholdMode = ThresholdMode.ABSOLUTE
) -> RuleBasedDetector:
    return RuleBasedDetector(rule, ThresholdTable({}), mode)


def test_detector_fires_when_all_conditions_hold():
    rule = SmellRule(
        smell_type=SmellType.LARGE_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(
            Condition("loc", Operator.GT, 200.0),
            Condition("number_of_methods", Operator.GT, 20.0),
        ),
    )
    entity = _entity()
    finding = _detector(rule).evaluate(
        entity, _vector(entity, loc=400.0, number_of_methods=30.0)
    )
    assert finding is not None
    assert finding.smell_type is SmellType.LARGE_CLASS


def test_all_combinator_needs_every_condition():
    rule = SmellRule(
        smell_type=SmellType.LARGE_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(
            Condition("loc", Operator.GT, 200.0),
            Condition("number_of_methods", Operator.GT, 20.0),
        ),
    )
    entity = _entity()
    assert (
        _detector(rule).evaluate(
            entity, _vector(entity, loc=400.0, number_of_methods=3.0)
        )
        is None
    )


def test_any_combinator_needs_only_one_condition():
    rule = SmellRule(
        smell_type=SmellType.COMPLEX_METHOD,
        entity_type=EntityType.METHOD,
        conditions=(
            Condition("cyclomatic_complexity", Operator.GT, 10.0),
            Condition("cognitive_complexity", Operator.GT, 15.0),
        ),
        combinator=Combinator.ANY,
    )
    entity = _entity("go", EntityType.METHOD)
    finding = _detector(rule).evaluate(
        entity,
        _vector(entity, cyclomatic_complexity=12.0, cognitive_complexity=3.0),
    )
    assert finding is not None


def test_detector_ignores_entities_of_the_wrong_type():
    rule = SmellRule(
        smell_type=SmellType.GOD_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(Condition("wmc", Operator.GT, 1.0),),
    )
    method = _entity("go", EntityType.METHOD)
    assert _detector(rule).evaluate(method, _vector(method, wmc=99.0)) is None


def test_exempt_entity_is_never_flagged():
    rule = SmellRule(
        smell_type=SmellType.LAZY_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(Condition("loc", Operator.LT, 25.0),),
        exemption=Exemption(base_class_patterns=(".*Error",)),
    )
    entity = _entity("CorruptArchiveError")
    features = _vector(entity, loc=3.0)

    assert _detector(rule).evaluate(entity, features, EntityFacts()) is not None
    assert (
        _detector(rule).evaluate(
            entity, features, EntityFacts(base_names=("ArchiveError",))
        )
        is None
    )


def test_severity_uses_the_weakest_satisfied_condition():
    """Taking the strongest would let one extreme metric mask an otherwise
    borderline finding and push every severity to Critical."""
    rule = SmellRule(
        smell_type=SmellType.LARGE_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(
            Condition("loc", Operator.GT, 100.0),
            Condition("number_of_methods", Operator.GT, 10.0),
        ),
    )
    entity = _entity()
    finding = _detector(rule).evaluate(
        entity, _vector(entity, loc=1000.0, number_of_methods=11.0)
    )
    assert finding is not None
    assert finding.severity is Severity.LOW


def test_finding_explains_every_condition_it_evaluated():
    rule = SmellRule(
        smell_type=SmellType.LARGE_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(Condition("loc", Operator.GT, 200.0),),
        rationale="Classes this size cannot be reviewed in one sitting.",
    )
    entity = _entity()
    finding = _detector(rule).evaluate(entity, _vector(entity, loc=500.0))

    assert finding is not None
    explanation = finding.explain()
    assert "loc = 500 > 200" in explanation
    assert "literature threshold" in explanation
    assert "cannot be reviewed" in explanation


def test_percentile_mode_falls_back_when_the_sample_is_too_small():
    rule = SmellRule(
        smell_type=SmellType.LARGE_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(Condition("loc", Operator.GT, 200.0, percentile=90.0),),
    )
    entity = _entity()
    finding = _detector(rule, ThresholdMode.PERCENTILE).evaluate(
        entity, _vector(entity, loc=500.0)
    )

    assert finding is not None
    assert finding.outcomes[0].source is ThresholdMode.ABSOLUTE
    assert finding.outcomes[0].threshold == 200.0


def test_percentile_mode_uses_the_project_distribution_when_it_can():
    entity = _entity()
    table = ThresholdTable.from_vectors(
        [
            _vector(_entity(f"C{i}"), loc=float(i))
            for i in range(MIN_ENTITIES_FOR_PERCENTILES + 5)
        ]
    )
    rule = SmellRule(
        smell_type=SmellType.LARGE_CLASS,
        entity_type=EntityType.CLASS,
        conditions=(Condition("loc", Operator.GT, 200.0, percentile=90.0),),
    )
    detector = RuleBasedDetector(rule, table, ThresholdMode.PERCENTILE)
    finding = detector.evaluate(entity, _vector(entity, loc=100.0))

    assert finding is not None, "a project-relative outlier well under 200 LOC"
    assert finding.outcomes[0].source is ThresholdMode.PERCENTILE


# --------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------- #


#: Collaborators for the god-class fixture. Each has real behaviour and its
#: own state, so none of them trips Lazy Class or Data Class -- the fixture
#: has to isolate the smell it is testing for.
_COLLABORATORS = (
    "Ledger", "Mailer", "Repo", "Cache", "Auditor", "Pricer", "Shipper", "Taxman",
)


def _god_class_source() -> str:
    """A class that is genuinely a God Class on every axis the rule checks.

    Built to satisfy all three conditions independently -- WMC well past 47,
    LCOM* past 0.725 because each method owns a different field, and CBO past
    5 because it reaches into eight collaborators. A fixture that only trips
    one of the three would pass while the rule was broken.
    """
    fields = "\n".join(f"        self.f{i} = {i}" for i in range(14))
    methods = []
    for i in range(26):
        collaborator = _COLLABORATORS[i % len(_COLLABORATORS)]
        other = _COLLABORATORS[(i + 3) % len(_COLLABORATORS)]
        methods.append(
            f"    def handle_{i}(self, x, y):\n"
            f"        if x and y:\n"
            f"            for j in range(y):\n"
            f"                if j > {i}:\n"
            f"                    self.f{i % 14} = "
            f"{collaborator}().run(j) + {other}().run(j)\n"
            f"        elif x:\n"
            f"            self.f{i % 14} = {collaborator}().run(0)\n"
            f"        return self.f{i % 14}\n"
        )
    return (
        "class OrderProcessor:\n    def __init__(self):\n"
        f"{fields}\n\n" + "\n".join(methods)
    )


def _collaborator_source() -> str:
    return "\n\n".join(
        f"class {name}:\n"
        f"    def __init__(self):\n        self.state = 0\n\n"
        f"    def run(self, j):\n"
        f"        self.state += j\n        return self.state\n\n"
        f"    def reset(self):\n"
        f"        self.state = 0\n        return self.state\n"
        for name in _COLLABORATORS
    )


GOD_CLASS_PROJECT = {
    "big.py": _god_class_source(),
    "collab.py": _collaborator_source(),
}


def test_end_to_end_detects_a_god_class(engine, tmp_path):
    analysis = _analyze(engine, tmp_path, GOD_CLASS_PROJECT)
    report = DetectionEngine(load_rules()).detect(analysis)

    god = report.by_smell(SmellType.GOD_CLASS)
    assert len(god) == 1
    assert god[0].entity.name == "OrderProcessor"
    assert SmellType.LARGE_CLASS in {f.smell_type for f in report.findings}


def test_god_class_rule_does_not_flag_healthy_collaborators(engine, tmp_path):
    """Eight small, cohesive classes sit alongside the god class. Flagging any
    of them would mean the rule is reading project size, not class quality."""
    analysis = _analyze(engine, tmp_path, GOD_CLASS_PROJECT)
    report = DetectionEngine(load_rules()).detect(analysis)

    flagged = {f.entity.name for f in report.findings}
    assert flagged & set(_COLLABORATORS) == set()


def test_end_to_end_finds_nothing_in_clean_code(engine, tmp_path):
    """A rule set that fires on tidy code is not usable as a baseline."""
    analysis = _analyze(
        engine,
        tmp_path,
        {
            "clean.py": (
                "class Greeter:\n"
                '    """Says hello."""\n\n'
                "    def __init__(self, name):\n"
                "        self.name = name\n\n"
                "    def greet(self):\n"
                "        return f'hello {self.name}'\n\n"
                "    def farewell(self):\n"
                "        return f'bye {self.name}'\n"
            )
        },
    )
    report = DetectionEngine(load_rules()).detect(analysis)
    assert report.findings == ()


def test_end_to_end_does_not_flag_exception_subclasses(engine, tmp_path):
    """Regression: the first run of these rules flagged every exception class
    in this project as Lazy Class. An exception subclass is *meant* to be
    three lines with no methods."""
    analysis = _analyze(
        engine,
        tmp_path,
        {
            "errors.py": (
                "class AppError(Exception):\n"
                '    """Base error."""\n\n'
                "class NotFoundError(AppError):\n"
                "    code = 'not_found'\n\n"
                "class ConflictError(AppError):\n"
                "    code = 'conflict'\n"
            )
        },
    )
    report = DetectionEngine(load_rules()).detect(analysis)

    assert report.by_smell(SmellType.LAZY_CLASS) == ()
    assert report.by_smell(SmellType.REFUSED_BEQUEST) == ()


def test_end_to_end_does_not_flag_enums_as_data_classes(engine, tmp_path):
    analysis = _analyze(
        engine,
        tmp_path,
        {
            "kinds.py": (
                "from enum import StrEnum\n\n"
                "class Kind(StrEnum):\n"
                "    ALPHA = 'alpha'\n"
                "    BETA = 'beta'\n"
                "    GAMMA = 'gamma'\n"
                "    DELTA = 'delta'\n"
            )
        },
    )
    report = DetectionEngine(load_rules()).detect(analysis)
    assert report.by_smell(SmellType.DATA_CLASS) == ()


def test_end_to_end_does_not_treat_stdlib_calls_as_feature_envy(engine, tmp_path):
    """Regression: `ast.walk(x)` and `os.path.join(...)` are qualified names,
    not another object's data. Counting them made foreign_access_ratio a proxy
    for 'uses the standard library' and was the single largest false-positive
    source in the first run."""
    analysis = _analyze(
        engine,
        tmp_path,
        {
            "util.py": (
                "import os\nimport json\n\n"
                "class Loader:\n"
                "    def __init__(self, base):\n        self.base = base\n\n"
                "    def load(self, name):\n"
                "        path = os.path.join(self.base, name)\n"
                "        with open(path) as handle:\n"
                "            return json.loads(handle.read())\n"
            )
        },
    )
    report = DetectionEngine(load_rules()).detect(analysis)
    assert report.by_smell(SmellType.FEATURE_ENVY) == ()


def test_report_orders_findings_by_severity_then_location(engine, tmp_path):
    analysis = _analyze(engine, tmp_path, GOD_CLASS_PROJECT)
    report = DetectionEngine(load_rules()).detect(analysis)

    ranks = [f.severity.rank for f in report.findings]
    assert ranks == sorted(ranks, reverse=True)


def test_report_summarises_counts(engine, tmp_path):
    analysis = _analyze(engine, tmp_path, GOD_CLASS_PROJECT)
    report = DetectionEngine(load_rules()).detect(analysis)
    summary = report.summary()

    assert summary["findings"] == len(report.findings)
    assert sum(report.counts_by_smell().values()) == len(report.findings)
    assert sum(report.counts_by_severity().values()) == len(report.findings)


def test_percentile_mode_skips_rules_without_percentiles(engine, tmp_path):
    """A rule with no percentile declared cannot run project-relative, and
    silently applying its absolute threshold would misreport the mode."""
    analysis = _analyze(engine, tmp_path, {"m.py": "class S:\n    pass\n"})
    report = DetectionEngine(load_rules(), ThresholdMode.PERCENTILE).detect(analysis)

    assert report.skipped_rules
    assert "lazy_class" in report.skipped_rules


def test_detection_is_deterministic(engine, tmp_path):
    """Two runs over the same source must produce byte-identical findings, or
    the baseline numbers in the paper are not reproducible."""
    analysis = _analyze(engine, tmp_path, GOD_CLASS_PROJECT)
    first = DetectionEngine(load_rules()).detect(analysis)
    second = DetectionEngine(load_rules()).detect(analysis)

    assert [
        (f.smell_type, f.entity.qualified_name, f.severity) for f in first.findings
    ] == [
        (f.smell_type, f.entity.qualified_name, f.severity) for f in second.findings
    ]


# --------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------- #


def test_finding_serialises_its_full_condition_trail(engine, tmp_path):
    """The export is what the human-labelling workflow consumes. A candidate
    without the measurements behind it gives an adjudicator nothing to judge,
    and a label produced that way is barely better than the rule's guess."""
    analysis = _analyze(engine, tmp_path, GOD_CLASS_PROJECT)
    report = DetectionEngine(load_rules()).detect(analysis)
    payload = report.by_smell(SmellType.GOD_CLASS)[0].to_dict()

    assert payload["smell"] == "god_class"
    assert payload["entity"]["qualified_name"].endswith("OrderProcessor")
    assert payload["entity"]["start_line"] > 0
    assert payload["references"]
    assert len(payload["conditions"]) == 3
    for condition in payload["conditions"]:
        assert {"metric", "observed", "threshold", "satisfied"} <= set(condition)


def test_report_export_is_json_serialisable(engine, tmp_path):
    import json

    analysis = _analyze(engine, tmp_path, GOD_CLASS_PROJECT)
    report = DetectionEngine(load_rules()).detect(analysis)

    restored = json.loads(json.dumps(report.to_dict()))
    assert restored["summary"]["findings"] == len(report.findings)
    assert len(restored["findings"]) == len(report.findings)


# --------------------------------------------------------------------- #
# Rule file: severity and exemption edge cases
# --------------------------------------------------------------------- #


def _rule_file(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nsmells:\n  large_class:\n    entity_type: class\n"
        f"{extra}"
        "    conditions:\n      - metric: loc\n        op: '>'\n"
        "        absolute: 200\n",
        encoding="utf-8",
    )
    return path


def test_custom_severity_bands_override_the_defaults(tmp_path: Path):
    rule = load_rules(
        _rule_file(
            tmp_path,
            "    severity:\n      low: 1.0\n      critical: 10.0\n",
        )
    )[0]

    assert rule.severity_for(9.0) is Severity.LOW
    assert rule.severity_for(10.0) is Severity.CRITICAL


def test_severity_band_none_is_rejected(tmp_path: Path):
    """`none` means 'no smell'. Giving it a multiplier would let a rule fire
    and simultaneously claim nothing is wrong."""
    with pytest.raises(RuleConfigError, match="cannot have a multiplier"):
        load_rules(_rule_file(tmp_path, "    severity:\n      none: 1.0\n"))


def test_unknown_severity_band_is_rejected(tmp_path: Path):
    with pytest.raises(RuleConfigError, match="unknown severity band"):
        load_rules(_rule_file(tmp_path, "    severity:\n      spicy: 2.0\n"))


def test_severity_must_be_a_mapping(tmp_path: Path):
    with pytest.raises(RuleConfigError, match="severity must be a mapping"):
        load_rules(_rule_file(tmp_path, "    severity: [1, 2]\n"))


def test_exempt_if_accepts_a_bare_set_name(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\n"
        "exemption_sets:\n  enums:\n    base_class_matches: ['StrEnum']\n"
        "smells:\n  large_class:\n    entity_type: class\n"
        "    exempt_if: enums\n"
        "    conditions:\n      - metric: loc\n        op: '>'\n"
        "        absolute: 200\n",
        encoding="utf-8",
    )
    rule = load_rules(path)[0]
    assert rule.exempts(_entity(), EntityFacts(base_names=("StrEnum",)))


def test_inline_and_shared_exemptions_merge(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\n"
        "exemption_sets:\n  enums:\n    base_class_matches: ['StrEnum']\n"
        "smells:\n  large_class:\n    entity_type: class\n"
        "    exempt_if:\n      use: [enums]\n"
        "      decorated_with: ['dataclass']\n"
        "    conditions:\n      - metric: loc\n        op: '>'\n"
        "        absolute: 200\n",
        encoding="utf-8",
    )
    rule = load_rules(path)[0]

    assert rule.exempts(_entity(), EntityFacts(base_names=("StrEnum",)))
    assert rule.exempts(_entity(), EntityFacts(decorators=("dataclass",)))


def test_exemption_patterns_must_be_a_list(tmp_path: Path):
    with pytest.raises(RuleConfigError, match="patterns must be a list"):
        load_rules(
            _rule_file(tmp_path, "    exempt_if:\n      base_class_matches: nope\n")
        )


def test_exemption_sets_must_be_a_mapping(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nexemption_sets: [1, 2]\n"
        "smells:\n  large_class:\n    entity_type: class\n"
        "    conditions:\n      - metric: loc\n        op: '>'\n"
        "        absolute: 200\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleConfigError, match="exemption_sets must be a mapping"):
        load_rules(path)


def test_conditions_must_be_a_list_of_mappings(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nsmells:\n  large_class:\n    entity_type: class\n"
        "    conditions:\n      - just a string\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleConfigError, match="condition must be a mapping"):
        load_rules(path)


def test_condition_requires_a_metric_name(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "version: 1\nsmells:\n  large_class:\n    entity_type: class\n"
        "    conditions:\n      - op: '>'\n        absolute: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleConfigError, match="missing a metric"):
        load_rules(path)


def test_rule_body_must_be_a_mapping(tmp_path: Path):
    path = tmp_path / "rules.yaml"
    path.write_text("version: 1\nsmells:\n  large_class: nope\n", encoding="utf-8")
    with pytest.raises(RuleConfigError, match="rule body must be a mapping"):
        load_rules(path)


def test_unknown_combinator_is_rejected(tmp_path: Path):
    with pytest.raises(RuleConfigError, match="combinator must be"):
        load_rules(_rule_file(tmp_path, "    combinator: maybe\n"))
