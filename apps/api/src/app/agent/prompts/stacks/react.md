React-specific rules:
- `useState` setters accept functional updates: `setX(prev => ...)`
- Suggestions for race conditions: use functional updates, NOT useEffect dependencies
- Never suggest adding useEffect for derived state — use useMemo or inline computation
