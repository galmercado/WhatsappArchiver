import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api, ApiError } from "../api/client";
import { App } from "../App";

afterEach(() => vi.restoreAllMocks());

const status = (over: Record<string, unknown>) =>
  vi.spyOn(api, "status").mockResolvedValue({ auth_mode: "password_totp", authenticated: false, vault_unlocked: false, csrf_token: null, ...over } as never);

it("password mode: shows credentials form, strips non-digits from the code, reports bad credentials generically", async () => {
  status({});
  const login = vi.spyOn(api, "login").mockRejectedValue(new ApiError(401, "invalid credentials"));
  render(<App />);
  const pw = await screen.findByLabelText("Password");
  const code = screen.getByLabelText("6-digit code");
  fireEvent.change(pw, { target: { value: "hunter2" } });
  fireEvent.change(code, { target: { value: "12ab34cd56" } });
  expect(code).toHaveValue("123456");
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials.");
  expect(login).toHaveBeenCalledWith("hunter2", "123456");
  expect(screen.getByLabelText("6-digit code")).toHaveValue(""); // code cleared after a failure
});

it("rate limiting is explained with the server's wait time", async () => {
  status({});
  vi.spyOn(api, "login").mockRejectedValue(new ApiError(429, "too many attempts", 30));
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "x" } });
  fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 30s");
});

it("google mode: a single sign-in link, no password fields", async () => {
  status({ auth_mode: "google" });
  render(<App />);
  const link = await screen.findByRole("link", { name: "Continue with Google" });
  expect(link).toHaveAttribute("href", "/auth/google/start");
  expect(screen.queryByLabelText("Password")).toBeNull();
});

it("authenticated but locked: asks for the vault passphrase and clears it after use", async () => {
  status({ authenticated: true, csrf_token: "t" });
  const unlock = vi.spyOn(api, "unlock").mockRejectedValue(new ApiError(401, "unlock failed"));
  render(<App />);
  const input = await screen.findByLabelText("Vault passphrase");
  fireEvent.change(input, { target: { value: "wrong-passphrase" } });
  fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("did not unlock");
  expect(unlock).toHaveBeenCalledWith("wrong-passphrase");
  await waitFor(() => expect(screen.getByLabelText("Vault passphrase")).toHaveValue(""));
  expect(screen.getByLabelText("Vault passphrase")).toHaveAttribute("type", "password");
});

it("unreachable server shows a clear fatal screen", async () => {
  vi.spyOn(api, "status").mockRejectedValue(new ApiError(0, "Network error"));
  render(<App />);
  expect(await screen.findByText("Cannot reach the server")).toBeInTheDocument();
});

it("passwords are never put in the DOM as text or URLs", async () => {
  status({});
  render(<App />);
  const pw = await screen.findByLabelText("Password");
  expect(pw).toHaveAttribute("type", "password");
  expect(pw).toHaveAttribute("autocomplete", "current-password");
  expect(window.location.href).not.toMatch(/password|passphrase/i);
});
