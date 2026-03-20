import { useEffect, useRef } from "react";

const PARTICLE_COUNT = 1000;
const TAU = Math.PI * 2;

interface Particle {
  startX: number;
  startY: number;
  targetX: number;
  targetY: number;
  alpha: number;
  size: number;
  phase: number;
}

function lerp(from: number, to: number, progress: number) {
  return from + (to - from) * progress;
}

function easeOutCubic(value: number) {
  return 1 - ((1 - value) ** 3);
}

function randomPointInEllipse(centerX: number, centerY: number, radiusX: number, radiusY: number) {
  const angle = Math.random() * TAU;
  const radius = Math.sqrt(Math.random());
  return {
    x: centerX + Math.cos(angle) * radiusX * radius,
    y: centerY + Math.sin(angle) * radiusY * radius,
  };
}

function randomPointInCapsule(x1: number, y1: number, x2: number, y2: number, radius: number) {
  const t = Math.random();
  const baseX = lerp(x1, x2, t);
  const baseY = lerp(y1, y2, t);
  const angle = Math.random() * TAU;
  const distance = Math.sqrt(Math.random()) * radius;
  return {
    x: baseX + Math.cos(angle) * distance,
    y: baseY + Math.sin(angle) * distance,
  };
}

function sampleSilhouetteTarget(width: number, height: number) {
  const centerX = width / 2;
  const centerY = height / 2;
  const scale = Math.min(width, height) * 0.34;
  const bucket = Math.random();

  if (bucket < 0.16) {
    return randomPointInEllipse(centerX, centerY - scale * 0.38, scale * 0.16, scale * 0.18);
  }
  if (bucket < 0.48) {
    return randomPointInEllipse(centerX, centerY - scale * 0.02, scale * 0.24, scale * 0.34);
  }
  if (bucket < 0.62) {
    return randomPointInCapsule(
      centerX - scale * 0.12,
      centerY - scale * 0.08,
      centerX - scale * 0.34,
      centerY + scale * 0.26,
      scale * 0.05,
    );
  }
  if (bucket < 0.76) {
    return randomPointInCapsule(
      centerX + scale * 0.12,
      centerY - scale * 0.08,
      centerX + scale * 0.34,
      centerY + scale * 0.26,
      scale * 0.05,
    );
  }
  if (bucket < 0.88) {
    return randomPointInCapsule(
      centerX - scale * 0.08,
      centerY + scale * 0.28,
      centerX - scale * 0.2,
      centerY + scale * 0.72,
      scale * 0.06,
    );
  }

  return randomPointInCapsule(
    centerX + scale * 0.08,
    centerY + scale * 0.28,
    centerX + scale * 0.2,
    centerY + scale * 0.72,
    scale * 0.06,
  );
}

function buildParticles(width: number, height: number) {
  const centerX = width / 2;
  const centerY = height / 2;
  const spread = Math.max(width, height) * 0.62;
  const particles: Particle[] = [];

  for (let index = 0; index < PARTICLE_COUNT; index += 1) {
    const startAngle = Math.random() * TAU;
    const startRadius = spread * (0.3 + Math.random() * 0.75);
    const target = sampleSilhouetteTarget(width, height);

    particles.push({
      startX: centerX + Math.cos(startAngle) * startRadius,
      startY: centerY + Math.sin(startAngle) * startRadius,
      targetX: target.x,
      targetY: target.y,
      alpha: 0.4 + Math.random() * 0.5,
      size: 1 + Math.random(),
      phase: Math.random() * TAU,
    });
  }

  return particles;
}

export function ProgressParticleStage({
  progress,
  background = "#000000",
  particleColor = "#ffffff",
}: {
  progress: number;
  background?: string;
  particleColor?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const particlesRef = useRef<Particle[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const context = canvas.getContext("2d");
    if (!context) {
      return;
    }

    let frameHandle = 0;
    let disposed = false;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(Math.floor(rect.width), 1);
      const height = Math.max(Math.floor(rect.height), 1);
      canvas.width = width;
      canvas.height = height;
      particlesRef.current = buildParticles(width, height);
    };

    const render = (time: number) => {
      if (disposed) {
        return;
      }

      const width = canvas.width;
      const height = canvas.height;
      const easedProgress = easeOutCubic(Math.min(Math.max(progress / 100, 0), 1));

      context.clearRect(0, 0, width, height);
      context.fillStyle = background;
      context.fillRect(0, 0, width, height);

      particlesRef.current.forEach((particle) => {
        const drift = (1 - easedProgress) * 22;
        const pulse = 0.7 + Math.sin(time * 0.0012 + particle.phase) * 0.3;
        const x = lerp(particle.startX, particle.targetX, easedProgress)
          + Math.cos(time * 0.001 + particle.phase) * drift;
        const y = lerp(particle.startY, particle.targetY, easedProgress)
          + Math.sin(time * 0.0013 + particle.phase) * drift;

        context.beginPath();
        context.globalAlpha = particle.alpha * pulse;
        context.fillStyle = particleColor;
        context.arc(x, y, particle.size, 0, TAU);
        context.fill();
      });
      context.globalAlpha = 1;

      frameHandle = window.requestAnimationFrame(render);
    };

    const resizeObserver = new ResizeObserver(() => resize());
    resizeObserver.observe(canvas);
    resize();
    frameHandle = window.requestAnimationFrame(render);

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      window.cancelAnimationFrame(frameHandle);
    };
  }, [background, particleColor, progress]);

  return <canvas ref={canvasRef} className="absolute inset-0 size-full" />;
}
