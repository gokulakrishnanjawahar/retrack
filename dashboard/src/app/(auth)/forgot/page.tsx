import type { Metadata } from "next";
import { ForgotForm } from "@/components/auth/simple-form";

export const metadata: Metadata = { title: "Reset password" };

export default function ForgotPage() {
  return <ForgotForm />;
}
