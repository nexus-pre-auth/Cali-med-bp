import Link from "next/link";
import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

async function getProject(projectId: string) {
  const supabase = createClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();

  if (authError || !user) {
    return null;
  }

  const { data, error } = await supabase
    .from("projects")
    .select("*")
    .eq("id", projectId)
    .eq("user_id", user.id)
    .single();

  if (error) return null;
  return data;
}

async function getReviews(projectId: string) {
  const supabase = createClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();

  if (authError || !user) {
    return [];
  }

  const { data, error } = await supabase
    .from("reviews")
    .select("*")
    .eq("project_id", projectId)
    .order("created_at", { ascending: false });

  if (error) return [];
  return data ?? [];
}

export default async function ProjectDetailPage({ params }: { params: { id: string } }) {
  const project = await getProject(params.id);
  if (!project) notFound();

  const reviews = await getReviews(params.id);

  return (
    <main className="page-shell dashboard-shell">
      <div className="section-header">
        <div>
          <p className="eyebrow">Project</p>
          <h1>{project.name}</h1>
        </div>
        <div className="header-actions">
          <Link href="/dashboard" className="secondary-button">Back to dashboard</Link>
        </div>
      </div>

      <div className="welcome-panel">
        <h2>Project overview</h2>
        <p>{project.facility_type}</p>
        <p>{project.notes || "No additional notes provided."}</p>
      </div>

      {reviews.length === 0 ? (
        <div className="empty-state">
          <h3>No review results yet</h3>
          <p>Run a compliance review to generate findings for this project.</p>
        </div>
      ) : (
        <div className="project-grid">
          {reviews.map((review: any) => (
            <article key={review.id} className="project-card">
              <div className="project-topline">
                <span className="pill">{review.risk_level}</span>
              </div>
              <h3>{review.title}</h3>
              <p>{review.summary}</p>
              <p>Score: {review.score}</p>
              <ul>
                {(review.findings ?? []).map((finding: any, index: number) => (
                  <li key={`${review.id}-${index}`}>
                    {finding.code}: {finding.title}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
