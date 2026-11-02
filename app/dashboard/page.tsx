"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function DashboardPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<any[]>([]);
  const [userEmail, setUserEmail] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        router.push("/login");
        return;
      }

      setUserEmail(session.user.email ?? "");

      const { data, error } = await supabase
        .from("projects")
        .select("*")
        .eq("user_id", session.user.id)
        .order("created_at", { ascending: false });

      if (!error) setProjects(data ?? []);
      setLoading(false);
    };

    load();
  }, [router]);

  async function signOut() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  }

  return (
    <main className="page-shell dashboard-shell">
      <div className="section-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Dashboard</h1>
        </div>
        <div className="header-actions">
          <a href="/projects/new" className="primary-button">New project</a>
          <button className="secondary-button" onClick={signOut}>Sign out</button>
        </div>
      </div>

      <div className="welcome-panel">
        <h2>Welcome back</h2>
        <p>{userEmail || "Loading user..."}</p>
      </div>

      {loading ? (
        <p>Loading projects...</p>
      ) : projects.length === 0 ? (
        <div className="empty-state">
          <h3>No projects yet</h3>
          <p>Create your first healthcare review project to begin.</p>
          <a href="/projects/new" className="primary-button">Create project</a>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map((project) => (
            <article key={project.id} className="project-card">
              <div className="project-topline">
                <span className="pill">{project.status}</span>
              </div>
              <h3>{project.name}</h3>
              <p>{project.facility_type}</p>
              <small>{new Date(project.created_at).toLocaleDateString()}</small>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
