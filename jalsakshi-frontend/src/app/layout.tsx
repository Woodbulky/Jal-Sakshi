import type { Metadata } from 'next';
import './globals.css';
import IconSprite from '@/components/icons/SpriteSheet';

export const metadata: Metadata = {
  title: 'JAL-SAKSHI — Agentic Water-Supply Monitoring',
  description: 'Real-time AI-powered water infrastructure monitoring for Jal Jeevan Mission',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <IconSprite />
        {children}
      </body>
    </html>
  );
}
