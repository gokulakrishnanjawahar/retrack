"use client";

import { ArrowLeft, Loader2, MailCheck } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useActionState } from "react";
import { requestPasswordReset, updatePassword, type AuthState } from "@/app/(auth)/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ForgotForm() {
  const [state, action, pending] = useActionState<AuthState, FormData>(requestPasswordReset, undefined);
  if (state?.notice) {
    return (
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
        <div className="flex size-12 items-center justify-center rounded-xl border border-border bg-brand-soft">
          <MailCheck className="size-5 text-brand" />
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight">Check your inbox</h2>
          <p className="text-sm text-muted-foreground">
            If an account exists for <span className="text-foreground">{state.notice}</span>, a reset
            link is on its way.
          </p>
        </div>
        <BackToSignIn />
      </motion.div>
    );
  }
  return (
    <div className="space-y-7">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">Reset your password</h2>
        <p className="text-sm text-muted-foreground">We will email you a link to choose a new one.</p>
      </div>
      <form action={action} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input id="email" name="email" type="email" autoComplete="email" required className="h-10" />
        </div>
        <ErrorText error={state?.error} />
        <Button type="submit" disabled={pending} className="h-10 w-full">
          {pending ? <Loader2 className="size-4 animate-spin" /> : "Send reset link"}
        </Button>
      </form>
      <BackToSignIn />
    </div>
  );
}

export function ResetForm() {
  const [state, action, pending] = useActionState<AuthState, FormData>(updatePassword, undefined);
  return (
    <div className="space-y-7">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">Choose a new password</h2>
        <p className="text-sm text-muted-foreground">At least 8 characters.</p>
      </div>
      <form action={action} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="password">New password</Label>
          <Input id="password" name="password" type="password" autoComplete="new-password" minLength={8} required className="h-10" />
        </div>
        <ErrorText error={state?.error} />
        <Button type="submit" disabled={pending} className="h-10 w-full">
          {pending ? <Loader2 className="size-4 animate-spin" /> : "Save password"}
        </Button>
      </form>
    </div>
  );
}

function ErrorText({ error }: { error?: string }) {
  return error ? (
    <p role="alert" className="rounded-md border border-danger/25 bg-danger/10 px-3 py-2 text-[13px] text-danger">
      {error}
    </p>
  ) : null;
}

function BackToSignIn() {
  return (
    <Link href="/login" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-3.5" /> Back to sign in
    </Link>
  );
}
