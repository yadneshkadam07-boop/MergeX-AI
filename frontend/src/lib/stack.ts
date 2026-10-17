/** The stack keys worth showing as badges, in the order they read best. */
const STACK_KEYS = ["frontend", "backend", "database", "build", "package_managers"] as const;

/**
 * Framework names from the detected stack.
 *
 * Named keys rather than every array in the object: the stack report also
 * carries `signals`, which is a list of objects, and rendering one as a
 * React child throws and blanks the page.
 */
export function stackBadgesFrom(stack: Record<string, unknown> | null): string[] {
  if (!stack) return [];
  return STACK_KEYS.flatMap((key) => {
    const value = stack[key];
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  });
}
