import { createContext, useContext } from "react";
export const WorkspaceContext = createContext(null);
export const useWorkspace = () => useContext(WorkspaceContext);
export const copy = (x) => JSON.parse(JSON.stringify(x));
export const freshId = () =>
  crypto.randomUUID?.() || String(Date.now()) + String(Math.random()).slice(2);
export const readJson = (s, fallback) => {
  try {
    return JSON.parse(s);
  } catch {
    return fallback;
  }
};
