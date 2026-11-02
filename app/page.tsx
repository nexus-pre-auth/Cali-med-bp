import Link from "next/link";

export default function HomePage() {
  return (
    <main className="page-shell">
      <section className="hero">
        <div className="badge">Supabase + Vercel Ready</div>
        <h1>Cali Med BP</h1>
        <p>
          A compliant healthcare facility review workspace with project tracking,
          audit history, and secure access for your team.
        </p>

        <div className="cta-row">
          <Link href="/login" className="primary-button">Get started</Link>
          <Link href="/dashboard" className="secondary-button">View dashboard</Link>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <strong>Secure</strong>
            <span>Supabase auth + project isolation</span>
          </div>
          <div className="stat-card">
            <strong>Deployable</strong>
            <span>Built for Vercel production hosting</span>
          </div>
          <div className="stat-card">
            <strong>Workflow</strong>
            <span>Projects, reviews, and team access</span>
          </div>
        </div>
      </section>
    </main>
  );
}
