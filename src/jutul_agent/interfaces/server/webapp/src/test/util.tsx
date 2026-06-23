import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { SessionProvider } from "../context";
import { Controller } from "../controller";
import { createSessionStore } from "../store";

/** Render UI wrapped in a fresh store + controller (no network, no socket). */
export function renderWithStore(ui: ReactElement) {
  const store = createSessionStore();
  const controller = new Controller(store);
  const utils = render(<SessionProvider value={{ store, controller }}>{ui}</SessionProvider>);
  return { store, controller, ...utils };
}
