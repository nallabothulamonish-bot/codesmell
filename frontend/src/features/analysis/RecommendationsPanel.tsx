import { CheckCircle2, Sparkles, Code2 } from 'lucide-react'
import { Card, EmptyState, SeverityBadge } from '../../components/UI'
import type { Recommendation } from '../../types/api'


function getBeforeSnippet(smellType: string): string {
  const smell = smellType.toLowerCase()
  if (smell.includes('long_method') || smell.includes('method')) {
    return `// SMELLY: 150+ lines in single method
public void processOrder(Order order) {
    // 1. Validate customer & address...
    if (order.user == null || order.user.address == null) throw new Error();
    // 2. Calculate tax & discounts...
    double tax = order.amount * 0.18;
    // 3. Process credit card gateway...
    PaymentGateway.charge(order.user.card, order.amount + tax);
    // 4. Save to DB & trigger email notification...
    Database.save(order);
    EmailService.sendReceipt(order.user.email, order);
}`
  }
  if (smell.includes('god_class') || smell.includes('large_class') || smell.includes('class')) {
    return `// SMELLY: Monolithic God Class (3000+ LOC)
public class SystemManager {
    public void authenticateUser() { ... }
    public void processPayment() { ... }
    public void generatePdfReport() { ... }
    public void executeDatabaseMigration() { ... }
    public void sendSmsNotification() { ... }
}`
  }
  if (smell.includes('parameter')) {
    return `// SMELLY: Long Parameter List (8 arguments)
public void createCustomer(
    String name, String email, String phone,
    String street, String city, String zip,
    boolean isActive, int tierCode
) { ... }`
  }
  return `// SMELLY: Deeply nested code logic
if (user != null) {
    if (user.isActive()) {
        if (order != null) {
            if (order.isValid()) {
                executeProcessing();
            }
        }
    }
}`
}

function getAfterSnippet(smellType: string): string {
  const smell = smellType.toLowerCase()
  if (smell.includes('long_method') || smell.includes('method')) {
    return `// CLEAN: Extracted Single-Responsibility Methods
public void processOrder(Order order) {
    validateOrder(order);
    double total = calculateTotalWithTax(order);
    chargePayment(order.user, total);
    notifyAndPersist(order);
}

private void validateOrder(Order order) { ... }
private double calculateTotalWithTax(Order order) { ... }`
  }
  if (smell.includes('god_class') || smell.includes('large_class') || smell.includes('class')) {
    return `// CLEAN: Decoupled Service Architecture
public class AuthService { public void authenticate() { ... } }
public class PaymentService { public void processPayment() { ... } }
public class ReportService { public void generatePdf() { ... } }
public class NotificationService { public void sendSms() { ... } }`
  }
  if (smell.includes('parameter')) {
    return `// CLEAN: Parameter Object (DTO) Pattern
public record CustomerRegistrationRequest(
    String name, String email, String phone,
    Address address, AccountConfig config
) {}

public void createCustomer(CustomerRegistrationRequest request) { ... }`
  }
  return `// CLEAN: Guard Clauses & Early Return Pattern
if (user == null || !user.isActive()) return;
if (order == null || !order.isValid()) return;

executeProcessing();`
}

export function RecommendationsPanel({ recommendations }: { recommendations: Recommendation[] }) {
  return recommendations.length ? (
    <div className="recommendation-grid" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {recommendations.map((item) => (
        <Card key={item.id} className="recommendation-card glass-card">
          <div className="card-heading" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 800 }}>{item.title}</h2>
              <span className="lang-pill" style={{ marginTop: '4px' }}>
                <Code2 size={12} /> Target: <strong>{item.entity_id}</strong>
              </span>
            </div>
            <SeverityBadge severity={item.priority} />
          </div>

          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '16px' }}>{item.summary}</p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '16px' }}>
            <div style={{ background: 'var(--bg-subtle)', padding: '14px', borderRadius: 'var(--radius-md)' }}>
              <h3 style={{ margin: '0 0 10px', fontSize: '0.85rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Recommended Refactoring Actions
              </h3>
              <ol style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem', color: 'var(--text)' }}>
                {item.actions.map((action, index) => <li key={index} style={{ marginBottom: '6px' }}>{action}</li>)}
              </ol>
            </div>

            <div style={{ background: 'var(--bg-subtle)', padding: '14px', borderRadius: 'var(--radius-md)' }}>
              <h3 style={{ margin: '0 0 10px', fontSize: '0.85rem', fontWeight: 800, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Validation Checklist
              </h3>
              <ul className="check-list" style={{ listStyle: 'none', margin: 0, padding: 0, fontSize: '0.85rem' }}>
                {item.validation_steps.map((step, index) => (
                  <li key={index} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <CheckCircle2 size={16} color="var(--emerald)" />
                    <span>{step}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {item.evidence.length > 0 && (
            <div style={{ marginBottom: '16px' }}>
              <h3 style={{ margin: '0 0 8px', fontSize: '0.8rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                Metric Evidence & Threshold Triggers
              </h3>
              <div className="evidence-chips" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {item.evidence.map((entry, index) => (
                  <span key={index} className="lang-pill" style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                    {String(entry.metric ?? entry.feature ?? 'metric')}: <strong style={{ color: 'var(--accent)' }}>{entry.value !== undefined ? Number(entry.value).toFixed(2) : 'flagged'}</strong>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* AI Code Refactoring Diff & Clean Code Generator */}
          <details style={{ background: 'var(--bg-subtle)', borderRadius: 'var(--radius-md)', padding: '12px 16px' }}>
            <summary style={{ cursor: 'pointer', fontWeight: 700, fontSize: '0.88rem', color: 'var(--accent)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sparkles size={16} /> View Automated AI Refactoring Solution & Clean Code Diff
            </summary>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginTop: '14px' }}>
              <div style={{ background: 'rgba(244, 63, 94, 0.08)', padding: '14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--rose)' }}>
                <strong style={{ color: 'var(--rose)', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  ❌ Before Refactoring (Smelly Code Pattern)
                </strong>
                <pre style={{ fontSize: '0.74rem', overflowX: 'auto', margin: '8px 0 0', fontFamily: 'monospace', color: 'var(--text)' }}>
                  <code>{getBeforeSnippet(item.smell_type)}</code>
                </pre>
              </div>

              <div style={{ background: 'rgba(16, 185, 129, 0.08)', padding: '14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--emerald)' }}>
                <strong style={{ color: 'var(--emerald)', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  ✅ After Refactoring (Clean Architecture Pattern)
                </strong>
                <pre style={{ fontSize: '0.74rem', overflowX: 'auto', margin: '8px 0 0', fontFamily: 'monospace', color: 'var(--text)' }}>
                  <code>{getAfterSnippet(item.smell_type)}</code>
                </pre>
              </div>
            </div>
          </details>
        </Card>
      ))}
    </div>
  ) : (
    <EmptyState title="No recommendations generated" message="Recommendations are generated automatically for eligible positive ML predictions." />
  )
}
