import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "../api/client";
import { qk } from "../api/hooks";
import * as s from "../api/schemas";
import { Button, Field, Input, errorMessage } from "../components/ui";

export const registerSchema = z.object({
  display_name: z.string().trim().min(1, "Enter your name"),
  email: z.string().trim().email("Enter a valid email"),
  password: z
    .string()
    .min(10, "At least 10 characters")
    .refine((p) => !/^[a-zA-Z]+$/.test(p) && !/^\d+$/.test(p), "Mix letters with digits or symbols"),
});
export const loginSchema = z.object({ email: z.string().trim().email("Enter a valid email"), password: z.string().min(1, "Enter your password") });

function AuthShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-2xl border border-line bg-panel p-6">
        <div className="mb-6 flex items-center gap-2 text-lg font-semibold"><img src="/favicon.svg" alt="" className="h-7 w-7" />EdgeLedger</div>
        <h1 className="mb-4 text-xl font-semibold">{title}</h1>
        {children}
      </div>
    </div>
  );
}

function useAuthForm<T extends z.ZodTypeAny>(schema: T, path: string) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: (body: z.infer<T>) => api(path, { method: "POST", body, schema: s.user }),
    onSuccess: (u) => { qc.setQueryData(qk.me, u); nav("/"); },
  });
  const submit = (raw: Record<string, string>) => {
    const r = schema.safeParse(raw);
    if (!r.success) {
      setErrors(Object.fromEntries(r.error.issues.map((i) => [String(i.path[0]), i.message])));
      return;
    }
    setErrors({});
    m.mutate(r.data);
  };
  return { errors, submit, m };
}

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { errors, submit, m } = useAuthForm(loginSchema, "/auth/login");
  return (
    <AuthShell title="Sign in">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit({ email, password }); }} noValidate>
        <Field label="Email" error={errors.email}><Input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password" error={errors.password}><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        {m.isError && <p role="alert" className="text-sm text-loss">{errorMessage(m.error)}</p>}
        <Button className="w-full" type="submit" disabled={m.isPending}>{m.isPending ? "Signing in…" : "Sign in"}</Button>
      </form>
      <p className="mt-4 text-sm text-muted">New here? <Link className="text-accent" to="/register">Create an account</Link></p>
    </AuthShell>
  );
}

export function RegisterPage() {
  const [v, setV] = useState({ display_name: "", email: "", password: "" });
  const { errors, submit, m } = useAuthForm(registerSchema, "/auth/register");
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value });
  return (
    <AuthShell title="Create your account">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(v); }} noValidate>
        <Field label="Name" error={errors.display_name}><Input value={v.display_name} onChange={set("display_name")} /></Field>
        <Field label="Email" error={errors.email}><Input type="email" autoComplete="email" value={v.email} onChange={set("email")} /></Field>
        <Field label="Password" error={errors.password} hint="10+ characters, not only letters or only digits">
          <Input type="password" autoComplete="new-password" value={v.password} onChange={set("password")} />
        </Field>
        {m.isError && <p role="alert" className="text-sm text-loss">{errorMessage(m.error)}</p>}
        <Button className="w-full" type="submit" disabled={m.isPending}>{m.isPending ? "Creating…" : "Create account"}</Button>
      </form>
      <p className="mt-4 text-sm text-muted">Already registered? <Link className="text-accent" to="/login">Sign in</Link></p>
    </AuthShell>
  );
}
