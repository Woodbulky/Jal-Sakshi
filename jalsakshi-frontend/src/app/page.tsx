'use client';
import { useRouter } from 'next/navigation';
import ParticleField from '@/components/canvas/ParticleField';
import WaveAnimation from '@/components/canvas/WaveAnimation';

export default function LandingPage() {
  const router = useRouter();

  return (
    <div className="landing-bg">
      {/* Particle background */}
      <ParticleField count={78} linkDistance={158} />

      {/* Top bar */}
      <div className="ln-top">
        <div className="wordmark">
          <div className="logo" style={{
            background: 'linear-gradient(140deg, #1583CE, #0E9FCB)',
            borderRadius: '50%',
            display: 'grid',
            placeItems: 'center',
          }}>
            <svg width="18" height="18" style={{ color: '#fff' }}>
              <use href="#i-drop" />
            </svg>
          </div>
          JAL-SAKSHI
        </div>
        <div className="row gap12">
          <span style={{ fontSize: 12, color: '#7FA6C2' }}>Jal Jeevan Mission</span>
        </div>
      </div>

      {/* Main content */}
      <div className="ln-body" style={{ animation: 'rise .9s cubic-bezier(.2,.7,.3,1) both' }}>
        <div style={{ animationDelay: '.1s', animation: 'rise .9s cubic-bezier(.2,.7,.3,1) both' }}>
          <div className="ln-title">JAL-SAKSHI</div>
          <div className="ln-sub" style={{ animationDelay: '.25s', animation: 'rise .9s cubic-bezier(.2,.7,.3,1) both' }}>
            Agentic <span className="accent">Water-Supply</span> Monitoring
          </div>
        </div>
        <p className="ln-p" style={{ animationDelay: '.4s', animation: 'rise .9s cubic-bezier(.2,.7,.3,1) both' }}>
          Real-time fault detection, autonomous diagnosis, field dispatch and sensor-verified
          restoration — powered by LangGraph and delivered over Telegram.
        </p>
        <div className="ln-cta" style={{ animationDelay: '.55s', animation: 'rise .9s cubic-bezier(.2,.7,.3,1) both' }}>
          <button
            className="cta-big"
            onClick={() => router.push('/service-area')}
          >
            <svg width="16" height="16">
              <use href="#i-drop" />
            </svg>
            Enter Monitoring Console
          </button>
        </div>
        <div className="ln-steps" style={{ animationDelay: '.7s', animation: 'rise .9s cubic-bezier(.2,.7,.3,1) both' }}>
          <span>Detect</span>
          <span>Diagnose</span>
          <span>Dispatch</span>
          <span>Verify</span>
        </div>
      </div>

      {/* Footer */}
      <div className="ln-foot">
        <div className="emblem">JJM</div>
        <div style={{ fontSize: 12, color: '#7FA6C2' }}>
          Jal Jeevan Mission · Department of Drinking Water &amp; Sanitation · Government of India
        </div>
      </div>

      {/* Waves */}
      <WaveAnimation />
    </div>
  );
}
