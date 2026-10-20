"use client";

import { animate, useInView, useMotionValue, useTransform, motion } from "motion/react";
import { useEffect, useRef } from "react";

// Counts up to `value` when it scrolls into view, and glides to new values as they change.
export function AnimatedNumber({
  value,
  format = (n) => Math.round(n).toLocaleString("en-US"),
  className,
}: {
  value: number;
  format?: (n: number) => string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const motionValue = useMotionValue(0);
  const text = useTransform(motionValue, format);

  useEffect(() => {
    if (!inView) return;
    const controls = animate(motionValue, value, { duration: 1.1, ease: [0.16, 1, 0.3, 1] });
    return () => controls.stop();
  }, [inView, motionValue, value]);

  return (
    <motion.span ref={ref} className={className}>
      {text}
    </motion.span>
  );
}
