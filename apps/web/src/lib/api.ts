const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export async function fetchReviews(repo: string) {
  const res = await fetch(`${API_BASE}/api/reviews?repo=${encodeURIComponent(repo)}`);
  if (!res.ok) throw new Error("Failed to fetch reviews");
  return res.json();
}
