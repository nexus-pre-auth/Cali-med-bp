import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { name, facilityType, notes } = body;

    if (!name || typeof name !== "string") {
      return NextResponse.json({ error: "Project name is required." }, { status: 400 });
    }

    const supabase = createClient();
    const {
      data: { user },
      error: authError,
    } = await supabase.auth.getUser();

    if (authError || !user) {
      return NextResponse.json({ error: "Authentication required." }, { status: 401 });
    }

    const { data, error } = await supabase
      .from("projects")
      .insert({
        user_id: user.id,
        name,
        facility_type: facilityType || "Healthcare Facility",
        notes: notes || "",
        status: "draft",
      })
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ success: true, project: data }, { status: 201 });
  } catch (error: any) {
    return NextResponse.json({ error: error.message || "Unexpected server error" }, { status: 500 });
  }
}

export async function GET() {
  try {
    const supabase = createClient();
    const {
      data: { user },
      error: authError,
    } = await supabase.auth.getUser();

    if (authError || !user) {
      return NextResponse.json({ error: "Authentication required." }, { status: 401 });
    }

    const { data, error } = await supabase
      .from("projects")
      .select("*")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false });

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ projects: data ?? [] }, { status: 200 });
  } catch (error: any) {
    return NextResponse.json({ error: error.message || "Unexpected server error" }, { status: 500 });
  }
}
