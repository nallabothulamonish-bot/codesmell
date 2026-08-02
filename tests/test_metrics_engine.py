"""Parser, object-oriented metrics and end-to-end engine tests.

The cross-file cases are the important ones. CBO, DIT, NOC and fan-in are the
metrics a single-pass engine gets silently wrong, so each is tested against a
project laid out across several modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codesmell.core.enums import EntityType, Language, SourceKind
from codesmell.core.models import SourceFile
from codesmell.ingestion.inventory import ProjectInventoryBuilder
from codesmell.languages.python import PythonParser
from codesmell.metrics import DEFAULT_CALCULATORS, MetricsEngine
from codesmell.metrics.engine import FeatureSchema, MetricComputationError
from codesmell.metrics.oo import (
    count_magic_numbers,
    foreign_access_ratio,
    lcom1,
    lcom_hs,
    local_variable_names,
    max_message_chain,
)


@pytest.fixture
def parser() -> PythonParser:
    return PythonParser()


def _source_file(path: str = "app/module.py") -> SourceFile:
    return SourceFile(
        relative_path=path,
        language=Language.PYTHON,
        size_bytes=1,
        line_count=1,
        sha256="0" * 64,
    )


@pytest.fixture
def engine() -> MetricsEngine:
    return MetricsEngine(
        parsers={Language.PYTHON: PythonParser()},
        calculators=DEFAULT_CALCULATORS,
    )


def _write_project(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _analyze(engine: MetricsEngine, root: Path, files: dict[str, str]):
    _write_project(root, files)
    inventory = ProjectInventoryBuilder(
        __import__(
            "codesmell.config.settings", fromlist=["IngestionSettings"]
        ).IngestionSettings()
    ).build(root, name="fixture", source_kind=SourceKind.DIRECTORY)
    return engine.analyze(root, inventory)


# --------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------- #


def test_parser_extracts_module_class_and_method(parser: PythonParser):
    parsed = parser.parse(
        "class Order:\n    def total(self):\n        return 0\n", _source_file()
    )
    by_type = {e.entity_type: e for e in parsed.entities}

    assert by_type[EntityType.MODULE].qualified_name == "app.module"
    assert by_type[EntityType.CLASS].qualified_name == "app.module.Order"
    assert by_type[EntityType.METHOD].qualified_name == "app.module.Order.total"


def test_module_level_function_is_a_function_not_a_method(parser: PythonParser):
    parsed = parser.parse("def helper():\n    return 1\n", _source_file())
    kinds = {e.entity_type for e in parsed.entities}
    assert EntityType.FUNCTION in kinds
    assert EntityType.METHOD not in kinds


def test_nested_function_is_captured(parser: PythonParser):
    """A closure can be a Long Method just as a top-level function can."""
    parsed = parser.parse(
        "def outer():\n    def inner():\n        return 1\n    return inner\n",
        _source_file(),
    )
    names = {e.qualified_name for e in parsed.entities}
    assert "app.module.outer.inner" in names


def test_async_function_is_captured(parser: PythonParser):
    parsed = parser.parse(
        "class S:\n    async def fetch(self):\n        return 1\n", _source_file()
    )
    assert any(e.name == "fetch" for e in parsed.entities)


def test_syntax_error_is_reported_not_raised(parser: PythonParser):
    """One unparseable file must never abort a thousand-file analysis."""
    parsed = parser.parse("def broken(:\n", _source_file())

    assert parsed.failed
    assert "SyntaxError" in parsed.parse_error
    assert parsed.entities == ()


def test_python2_source_fails_gracefully(parser: PythonParser):
    parsed = parser.parse("print 'hello'\n", _source_file())
    assert parsed.failed


def test_parser_records_base_classes(parser: PythonParser):
    parsed = parser.parse(
        "class A: pass\nclass B(A): pass\n", _source_file()
    )
    entity = next(e for e in parsed.entities if e.name == "B")
    assert parsed.facts_for(entity).base_names == ("A",)


def test_parser_counts_parameters_and_detects_self(parser: PythonParser):
    parsed = parser.parse(
        "class S:\n    def go(self, a, b, *args, **kwargs):\n        return a\n",
        _source_file(),
    )
    facts = parsed.facts_for(next(e for e in parsed.entities if e.name == "go"))

    assert facts.parameter_count == 5
    assert facts.has_self_parameter is True


def test_parser_distinguishes_declared_from_read_fields(parser: PythonParser):
    """`self.x = 1` declares a field; reading `self.y` does not."""
    parsed = parser.parse(
        "class S:\n"
        "    def __init__(self):\n        self.x = 1\n"
        "    def go(self):\n        return self.y\n",
        _source_file(),
    )
    klass = next(e for e in parsed.entities if e.name == "S")
    assert parsed.facts_for(klass).declared_fields == ("x",)


def test_parser_records_imports(parser: PythonParser):
    parsed = parser.parse(
        "from pkg.models import Order\nimport os.path as osp\n", _source_file()
    )
    assert parsed.imports["Order"] == "pkg.models.Order"
    assert parsed.imports["osp"] == "os.path"


def test_parser_records_decorators(parser: PythonParser):
    parsed = parser.parse(
        "class S:\n    @property\n    def x(self):\n        return 1\n",
        _source_file(),
    )
    facts = parsed.facts_for(next(e for e in parsed.entities if e.name == "x"))
    assert facts.decorators == ("property",)


# --------------------------------------------------------------------- #
# Cohesion
# --------------------------------------------------------------------- #


def test_lcom1_is_zero_for_a_perfectly_cohesive_class():
    """Every method touches the same field: no disjoint pairs."""
    assert lcom1([{"a"}, {"a"}, {"a"}]) == 0


def test_lcom1_counts_disjoint_pairs_minus_sharing_pairs():
    """Pairs: (a,b) disjoint, (a,c) disjoint, (b,c) disjoint -> 3 - 0 = 3."""
    assert lcom1([{"a"}, {"b"}, {"c"}]) == 3


def test_lcom1_subtracts_sharing_pairs_from_disjoint_pairs():
    """Methods {a},{a},{b}: pair 1-2 shares, pairs 1-3 and 2-3 do not.

    2 disjoint - 1 sharing = 1.
    """
    assert lcom1([{"a"}, {"a"}, {"b"}]) == 1


def test_lcom1_floors_at_zero():
    """Methods {a,b},{a},{b}: 2 sharing pairs, 1 disjoint -> -1, reported 0."""
    assert lcom1([{"a", "b"}, {"a"}, {"b"}]) == 0


def test_lcom1_needs_two_methods():
    assert lcom1([{"a"}]) == 0
    assert lcom1([]) == 0


def test_lcom_hs_is_zero_when_every_method_touches_every_field():
    assert lcom_hs([{"a", "b"}, {"a", "b"}], {"a", "b"}) == pytest.approx(0.0)


def test_lcom_hs_approaches_one_for_a_disjoint_class():
    """Each field touched by exactly one of three methods -- minimal cohesion."""
    value = lcom_hs([{"a"}, {"b"}, {"c"}], {"a", "b", "c"})
    assert value == pytest.approx(1.0)


def test_lcom_hs_needs_methods_and_fields():
    assert lcom_hs([{"a"}], {"a"}) == 0.0
    assert lcom_hs([{"a"}, {"b"}], set()) == 0.0


def test_lcom_hs_stays_bounded_while_lcom1_grows_quadratically():
    """The reason LCOM* is the better model feature.

    LCOM1 is a pair count, so it grows as O(m^2) with method count even when
    the cohesion *structure* is unchanged -- which confounds it with class
    size, the very thing a God Class label already tracks. A model given both
    would partly be reading size twice. LCOM* is normalised into [0, 1] and
    cannot run away like that.
    """
    small_fields = {"f0", "f1", "f2"}
    large_fields = {f"f{i}" for i in range(8)}
    small = [{f} for f in sorted(small_fields)]
    large = [{f} for f in sorted(large_fields)]

    # Same cohesion structure (every method owns one private field), but
    # LCOM1 is a pair count: C(3,2)=3 becomes C(8,2)=28.
    assert lcom1(small) == 3
    assert lcom1(large) == 28

    # LCOM* reports the same value, because the structure did not change.
    assert lcom_hs(small, small_fields) == pytest.approx(1.0)
    assert lcom_hs(large, large_fields) == pytest.approx(1.0)


# --------------------------------------------------------------------- #
# Method-level helpers
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = a\n", 0),
        ("x = a.b\n", 1),
        ("x = a.b.c\n", 2),
        ("x = a.b.c.d()\n", 3),
    ],
)
def test_max_message_chain(source: str, expected: int):
    import ast

    assert max_message_chain(ast.parse(source)) == expected


def test_local_variable_names_exclude_parameters():
    import ast

    node = ast.parse(
        "def f(a, b):\n    total = a\n    with open('x') as fh:\n        return fh\n"
    ).body[0]
    assert local_variable_names(node) == {"total", "fh"}


def test_magic_numbers_ignore_conventional_values():
    """0, 1, -1 and 2 appear in indexing idioms constantly -- flagging them
    produces noise rather than signal."""
    import ast

    node = ast.parse("x = items[0] + 1 - 2\ny = price * 1.075 + 4096\n")
    assert count_magic_numbers(node) == 2


def test_magic_numbers_ignore_booleans():
    import ast

    assert count_magic_numbers(ast.parse("flag = True\n")) == 0


def test_foreign_access_ratio_is_the_feature_envy_signal():
    import ast

    envious = ast.parse(
        "def f(self, order):\n"
        "    return order.total + order.tax + order.shipping\n"
    ).body[0]
    homely = ast.parse(
        "def f(self):\n    return self.total + self.tax + self.shipping\n"
    ).body[0]

    assert foreign_access_ratio(envious) == pytest.approx(1.0)
    assert foreign_access_ratio(homely) == pytest.approx(0.0)


def test_foreign_access_ratio_of_attribute_free_code_is_zero():
    import ast

    assert foreign_access_ratio(ast.parse("def f(a):\n    return a + 1\n")) == 0.0


# --------------------------------------------------------------------- #
# Cross-file metrics (the two-pass requirement)
# --------------------------------------------------------------------- #


def test_dit_resolves_inheritance_across_modules(engine, tmp_path):
    """DIT is undefined without a whole-project pass: `Base` lives elsewhere."""
    result = _analyze(
        engine,
        tmp_path,
        {
            "base.py": "class Base:\n    def run(self):\n        return 1\n",
            "middle.py": "from base import Base\n\nclass Middle(Base):\n    pass\n",
            "leaf.py": "from middle import Middle\n\nclass Leaf(Middle):\n    pass\n",
        },
    )
    features = {
        v.entity_id.split("::")[-1]: v for v in result.vectors_for(EntityType.CLASS)
    }

    assert features["base.Base"]["dit"] == 0
    assert features["middle.Middle"]["dit"] == 1
    assert features["leaf.Leaf"]["dit"] == 2


def test_noc_counts_subclasses_declared_in_other_modules(engine, tmp_path):
    result = _analyze(
        engine,
        tmp_path,
        {
            "base.py": "class Base:\n    pass\n",
            "a.py": "from base import Base\n\nclass A(Base):\n    pass\n",
            "b.py": "from base import Base\n\nclass B(Base):\n    pass\n",
        },
    )
    base = next(
        v for v in result.vectors_for(EntityType.CLASS) if "base.Base" in v.entity_id
    )
    assert base["noc"] == 2


def test_dit_is_zero_for_an_external_base_class(engine, tmp_path):
    """An unresolvable base yields depth 0 rather than a fabricated number.

    A wrong DIT is worse than a missing one: the model would learn from it.
    """
    result = _analyze(
        engine,
        tmp_path,
        {
            "m.py": "from django.db import models\n\n"
            "class Order(models.Model):\n    pass\n"
        },
    )
    order = next(v for v in result.vectors_for(EntityType.CLASS))

    assert order["dit"] == 0
    assert order["number_of_base_classes"] == 1
    assert result.context.unresolved_base_count == 1


def test_cbo_and_fan_in_are_directional(engine, tmp_path):
    """`Service` uses `Repository`, not the reverse."""
    result = _analyze(
        engine,
        tmp_path,
        {
            "repo.py": "class Repository:\n    def find(self, i):\n        return i\n",
            "service.py": (
                "from repo import Repository\n\n"
                "class Service:\n"
                "    def __init__(self):\n        self.repo = Repository()\n"
                "    def get(self, i):\n        return self.repo.find(i)\n"
            ),
        },
    )
    by_name = {
        v.entity_id.split("::")[-1]: v for v in result.vectors_for(EntityType.CLASS)
    }

    assert by_name["service.Service"]["cbo"] == 1
    assert by_name["service.Service"]["fan_in"] == 0
    assert by_name["repo.Repository"]["cbo"] == 0
    assert by_name["repo.Repository"]["fan_in"] == 1


def test_inheritance_cycle_does_not_hang(engine, tmp_path):
    """Illegal in Python, but reachable through name-resolution ambiguity."""
    result = _analyze(
        engine,
        tmp_path,
        {
            "a.py": "from b import B\n\nclass A(B):\n    pass\n",
            "b.py": "from a import A\n\nclass B(A):\n    pass\n",
        },
    )
    assert all(v["dit"] >= 0 for v in result.vectors_for(EntityType.CLASS))


def test_wmc_sums_method_complexity_not_method_count(engine, tmp_path):
    """Two methods, complexity 1 and 3 -> WMC 4, not 2."""
    result = _analyze(
        engine,
        tmp_path,
        {
            "m.py": (
                "class S:\n"
                "    def simple(self):\n        return 1\n"
                "    def branchy(self, a, b):\n"
                "        if a:\n            return 1\n"
                "        if b:\n            return 2\n"
                "        return 3\n"
            )
        },
    )
    klass = next(v for v in result.vectors_for(EntityType.CLASS))

    assert klass["number_of_methods"] == 2
    assert klass["wmc"] == 4
    assert klass["average_method_complexity"] == pytest.approx(2.0)


def test_rfc_counts_own_methods_plus_distinct_calls(engine, tmp_path):
    """2 methods + distinct calls {len, str, helper} = 5."""
    result = _analyze(
        engine,
        tmp_path,
        {
            "m.py": (
                "class S:\n"
                "    def a(self, x):\n        return len(x) + len(x)\n"
                "    def b(self, x):\n        return str(helper(x))\n"
            )
        },
    )
    klass = next(v for v in result.vectors_for(EntityType.CLASS))
    assert klass["rfc"] == 5


def test_public_method_count_excludes_underscored(engine, tmp_path):
    result = _analyze(
        engine,
        tmp_path,
        {
            "m.py": (
                "class S:\n"
                "    def public(self):\n        return 1\n"
                "    def _private(self):\n        return 2\n"
                "    def __init__(self):\n        self.x = 1\n"
            )
        },
    )
    klass = next(v for v in result.vectors_for(EntityType.CLASS))
    assert klass["number_of_methods"] == 3
    assert klass["number_of_public_methods"] == 1


# --------------------------------------------------------------------- #
# Engine and schema
# --------------------------------------------------------------------- #


def test_engine_produces_a_vector_for_every_entity(engine, tmp_path):
    result = _analyze(
        engine,
        tmp_path,
        {
            "m.py": "class S:\n    def go(self):\n        return 1\n\n"
            "def top():\n    return 2\n"
        },
    )
    # module + class + method + function
    assert result.entity_count == 4


def test_engine_survives_one_unparseable_file(engine, tmp_path):
    """The failure is recorded and the rest of the project still analyses."""
    result = _analyze(
        engine,
        tmp_path,
        {
            "good.py": "class Good:\n    def go(self):\n        return 1\n",
            "bad.py": "def broken(:\n",
        },
    )

    assert "bad.py" in result.parse_failures
    assert any(v.entity_type is EntityType.CLASS for v in result.features.values())


def test_class_and_method_feature_spaces_are_disjoint():
    """Roadmap section 1.1: LCOM is undefined for a method, nesting depth for
    a class. Mixing them into one matrix is the modelling error this guards."""
    schema = FeatureSchema.from_calculators(DEFAULT_CALCULATORS)
    class_only = set(schema.names_for(EntityType.CLASS))
    method_only = set(schema.names_for(EntityType.METHOD))

    assert "lcom_hs" in class_only and "lcom_hs" not in method_only
    assert "nesting_depth" in method_only and "nesting_depth" not in class_only
    assert "dit" in class_only and "dit" not in method_only


def test_schema_column_order_is_stable(engine, tmp_path):
    """Column order must not depend on dict iteration or plugin order, or a
    model trained today misreads a matrix built tomorrow."""
    schema = FeatureSchema.from_calculators(DEFAULT_CALCULATORS)
    reversed_schema = FeatureSchema.from_calculators(
        tuple(reversed(DEFAULT_CALCULATORS))
    )

    assert schema.names_for(EntityType.CLASS) == reversed_schema.names_for(
        EntityType.CLASS
    )


def test_schema_row_matches_declared_column_order(engine, tmp_path):
    result = _analyze(engine, tmp_path, {"m.py": "class S:\n    x = 1\n"})
    vector = next(iter(result.vectors_for(EntityType.CLASS)))

    row = result.schema.row(vector)
    names = result.schema.names_for(EntityType.CLASS)

    assert len(row) == len(names)
    assert row[names.index("number_of_fields")] == vector["number_of_fields"]


def test_schema_rejects_a_vector_missing_a_declared_feature():
    """A missing column becomes a silent NaN at training time and a column
    misalignment at inference. It has to be loud."""
    from codesmell.core.models import FeatureVector

    schema = FeatureSchema.from_calculators(DEFAULT_CALCULATORS)
    incomplete = FeatureVector(
        entity_id="x", entity_type=EntityType.CLASS, values={"wmc": 1.0}
    )

    with pytest.raises(MetricComputationError, match="missing schema features"):
        schema.row(incomplete)


def test_engine_rejects_a_calculator_that_omits_a_declared_metric(tmp_path):
    from codesmell.core.ports import MetricCalculator

    class Broken(MetricCalculator):
        @property
        def language(self) -> Language:
            return Language.PYTHON

        @property
        def metric_names(self) -> tuple[str, ...]:
            return ("promised", "never_delivered")

        @property
        def applies_to(self) -> frozenset[EntityType]:
            return frozenset({EntityType.CLASS})

        def compute(self, entity, context):
            return {"promised": 1.0}

    broken_engine = MetricsEngine(
        parsers={Language.PYTHON: PythonParser()}, calculators=(Broken(),)
    )

    with pytest.raises(MetricComputationError, match="omitted declared metrics"):
        _analyze(broken_engine, tmp_path, {"m.py": "class S:\n    pass\n"})


def test_engine_rejects_non_finite_metric_values(tmp_path):
    """NaN survives into a training matrix and poisons it quietly."""
    from codesmell.core.ports import MetricCalculator

    class Nan(MetricCalculator):
        @property
        def language(self) -> Language:
            return Language.PYTHON

        @property
        def metric_names(self) -> tuple[str, ...]:
            return ("bad",)

        @property
        def applies_to(self) -> frozenset[EntityType]:
            return frozenset({EntityType.CLASS})

        def compute(self, entity, context):
            return {"bad": float("nan")}

    nan_engine = MetricsEngine(
        parsers={Language.PYTHON: PythonParser()}, calculators=(Nan(),)
    )

    with pytest.raises(MetricComputationError, match="non-finite"):
        _analyze(nan_engine, tmp_path, {"m.py": "class S:\n    pass\n"})


def test_source_of_returns_exactly_the_entity_lines(engine, tmp_path):
    result = _analyze(
        engine,
        tmp_path,
        {"m.py": "x = 1\n\nclass S:\n    def go(self):\n        return 1\n"},
    )
    klass = next(
        e for e in result.context.entities() if e.entity_type is EntityType.CLASS
    )
    extracted = result.context.source_of(klass)

    assert extracted.startswith("class S:")
    assert "x = 1" not in extracted
    assert "return 1" in extracted


def test_analysis_reads_files_relative_to_the_reported_root(engine, tmp_path):
    """Regression: the ingestion service returned a root one level above the
    directory the inventory's relative paths were built from, so the metrics
    engine's `root / relative_path` missed every file. Every module recorded a
    parse failure, the analysis reported zero entities, and nothing raised."""
    from codesmell.config.settings import IngestionSettings
    from codesmell.ingestion.sandbox import WorkspaceManager
    from codesmell.ingestion.service import IngestionService

    project = tmp_path / "wrapper" / "myrepo-main"
    (project / "app").mkdir(parents=True)
    (project / "app" / "svc.py").write_text(
        "class Service:\n    def run(self):\n        return 1\n", encoding="utf-8"
    )

    manager = WorkspaceManager(tmp_path / "ws")
    with manager.session() as workspace:
        ingested = IngestionService(IngestionSettings(), workspace).ingest(
            tmp_path / "wrapper"
        )
        result = engine.analyze(ingested.root, ingested.inventory)

    assert result.parse_failures == {}
    assert result.entity_count > 0
    assert any(v.entity_type is EntityType.CLASS for v in result.features.values())
