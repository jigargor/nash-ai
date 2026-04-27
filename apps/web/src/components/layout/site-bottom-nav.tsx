import Link from "next/link";

interface FooterLink {
  href: string;
  label: string;
}

const FOOTER_LINKS: FooterLink[] = [
  { href: "/about", label: "About" },
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms & Conditions" },
];

export function SiteBottomNav() {
  return (
    <nav className="site-bottom-nav" aria-label="Site information">
      <ul className="site-bottom-nav-list">
        {FOOTER_LINKS.map((item) => (
          <li key={item.href}>
            <Link href={item.href} className="site-bottom-nav-link">
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
