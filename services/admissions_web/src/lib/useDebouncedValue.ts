import { useEffect, useState } from "react";

/**
 * The value once it has stopped changing for `ms` (300 ms: the end of a word being typed), so a
 * search asks the server once per pause, not once per letter. An emptied value applies at once.
 */
export function useDebouncedValue<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    if (value === "" || ms <= 0) {
      setSettled(value);
      return;
    }
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}
