export default function LoginPage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "2rem",
      }}
    >
      <section
        style={{
          width: "min(420px, 100%)",
          border: "1px solid var(--border)",
          background: "var(--card)",
          borderRadius: "0.75rem",
          padding: "1.5rem",
        }}
      >
        <h1 style={{ marginTop: 0, fontFamily: "var(--font-instrument-serif)" }}>Sign in</h1>
        <p style={{ color: "var(--text-muted)" }}>
          Authenticate with your GitHub account to access the review dashboard.
        </p>
        {/* Full navigation: OAuth route must not use client-side <Link>. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- API OAuth redirect */}
        <a
          href="/api/v1/auth/login"
          style={{
            display: "inline-block",
            marginTop: "1rem",
            padding: "0.65rem 1rem",
            borderRadius: "0.5rem",
            border: "1px solid var(--border)",
            background: "var(--background)",
            textDecoration: "none",
          }}
        >
          Login with GitHub
        </a>
      </section>
    </main>
  );
}
