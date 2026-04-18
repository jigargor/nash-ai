Django-specific rules:
- Flag missing transaction boundaries on multi-write operations.
- Prefer ORM parameterization and never raw SQL concatenated with user input.
- Middleware/auth assumptions should be verified before raising auth findings.
