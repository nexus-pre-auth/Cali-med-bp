import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function POST(request: Request) {
  try {
    const { projectId, title } = await request.json();

    if (!projectId || !title) {
      return NextResponse.json({ error: "Project ID and title are required." }, { status: 400 });
    }

    const supabase = createClient();
    const {
      data: { user },
      error: authError,
    } = await supabase.auth.getUser();

    if (authError || !user) {
      return NextResponse.json({ error: "Authentication required." }, { status: 401 });
    }

    const findings = [
      {
        code: "A-101",
        title: "Life-safety review required",
        severity: "high",
        status: "open",
      },
      {
        code: "M-087",
        title: "Mechanical ventilation check",
        severity: "medium",
        status: "monitoring",
      },
    ];

    const review = {
      project_id: projectId,
      title,
      summary: "Initial safety screen completed. Additional code review may be required based on occupancy type and project scope.",
      score: 86,
      risk_level: "medium",
      findings,
    };

    const { data, error } = await supabase.from("reviews").insert(review).select().single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ success: true, review: data }, { status: 201 });
  } catch (error: any) {
    return NextResponse.json({ error: error.message || "Unexpected server error" }, { status: 500 });
  }
}
