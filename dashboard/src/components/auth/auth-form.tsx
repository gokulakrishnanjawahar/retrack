"use client";

import { ArrowRight, Eye, EyeOff, Loader2, MailCheck } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useActionState, useState } from "react";
import { signIn, signUp, type AuthState } from "@/app/(auth)/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type Mode = "signin" | "signup";

export function AuthForm({ next, linkError }: { next: string; linkError: boolean }) {
  const [mode, setMode] = useState<Mode>("signin");
  const [showPassword, setShowPassword] = useState(false);
  const [signInState, signInAction, signingIn] = useActionState<AuthState, FormData>(signIn, undefined);
  const [signUpState, signUpAction, signingUp] = useActionState<AuthState, FormData>(signUp, undefined);
  const state = mode === "signin" ? signInState : signUpState;
  const pending = signingIn || signingUp;
  const error = state?.error ?? (linkError && !state ? "That link has expired. Sign in or request a new one." : undefined);

  if (mode === "signup" && signUpState?.notice) {
    return <CheckInbox email={signUpState.notice} onBack={() => setMode("signin")} />;
  }

  return (
    <div className="space-y-7">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">
          {mode === "signin" ? "Welcome back" : "Create your account"}
        </h2>
        <p className="text-sm text-muted-foreground">
          {mode === "signin"
            ? "Sign in to see what your agents have learned."
            : "Start capturing runs in under five minutes."}
        </p>
      </div>

      <div className="relative grid grid-cols-2 rounded-lg border border-border bg-white/[0.02] p-1">
        {(["signin", "signup"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "relative z-10 rounded-md py-1.5 text-[13px] font-medium transition-colors",
              mode === m ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {mode === m ? (
              <motion.span
                layoutId="auth-tab"
                className="absolute inset-0 -z-10 rounded-md bg-white/[0.07] ring-1 ring-white/10"
                transition={{ type: "spring", stiffness: 500, damping: 38 }}
              />
            ) : null}
            {m === "signin" ? "Sign in" : "Create account"}
          </button>
        ))}
      </div>

      <form action={mode === "signin" ? signInAction : signUpAction} className="space-y-4">
        <input type="hidden" name="next" value={next} />
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input id="email" name="email" type="email" autoComplete="email" placeholder="you@company.com" required className="h-10" />
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            {mode === "signin" ? (
              <Link href="/forgot" className="text-xs text-muted-foreground hover:text-foreground">
                Forgot password?
              </Link>
            ) : (
              <span className="text-xs text-faint">8+ characters</span>
            )}
          </div>
          <div className="relative">
            <Input
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              required
              minLength={mode === "signup" ? 8 : undefined}
              className="h-10 pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-faint hover:text-foreground"
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
        </div>

        <AnimatePresence>
          {error ? (
            <motion.p
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              role="alert"
              className="rounded-md border border-danger/25 bg-danger/10 px-3 py-2 text-[13px] text-danger"
            >
              {error}
            </motion.p>
          ) : null}
        </AnimatePresence>

        <Button type="submit" disabled={pending} className="group h-10 w-full text-[13.5px]">
          {pending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <>
              {mode === "signin" ? "Sign in" : "Create account"}
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </>
          )}
        </Button>
      </form>
    </div>
  );
}

function CheckInbox({ email, onBack }: { email: string; onBack: () => void }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-6 text-center">
      <div className="relative mx-auto flex size-14 items-center justify-center rounded-2xl border border-border bg-brand-soft">
        <span className="absolute inset-0 rounded-2xl animate-pulse-ring bg-brand/20" />
        <MailCheck className="relative size-6 text-brand" />
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">Check your inbox</h2>
        <p className="text-sm text-muted-foreground">
          We sent a confirmation link to <span className="text-foreground">{email}</span>. Open it on
          this device to finish setting up.
        </p>
      </div>
      <Button variant="ghost" onClick={onBack} className="text-muted-foreground">
        Back to sign in
      </Button>
    </motion.div>
  );
}
