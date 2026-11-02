"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function NewProjectPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [facilityType, setFacilityType] = useState("Healthcare Facility");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, facilityType, notes }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Unable to create project");

      setMessage("Project created successfully.");
      router.push("/dashboard");
      router.refresh();
    } catch (error: any) {
      setMessage(error.message || "Failed to create project");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page-shell auth-shell">
      <div className="auth-card wide-card">
        <h1>Create a new project</h1>
        <p>Set up a new compliance review workspace.</p>

        <form onSubmit={handleSubmit} className="auth-form">
          <label>
            Project name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Valley General Hospital" required />
          </label>

          <label>
            Facility type
            <select value={facilityType} onChange={(e) => setFacilityType(e.target.value)}>
              <option>Healthcare Facility</option>
              <option>Acute Care Hospital</option>
              <option>Surgical Center</option>
              <option>Behavioral Health</option>
              <option>Outpatient Clinic</option>
            </select>
          </label>

          <label>
            Notes
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Project scope, notes, or checklist items" rows={6} />
          </label>

          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? "Creating..." : "Create project"}
          </button>
        </form>

        {message && <p className="message">{message}</p>}
      </div>
    </main>
  );
}
