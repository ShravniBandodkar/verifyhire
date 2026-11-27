import './globals.css';
import type { Metadata, Viewport } from 'next';
import PwaRegister from '@/components/PwaRegister';

export const metadata: Metadata = {
  title: 'VerifyHire — Verified Resume Registry',
  description: 'AI-native, Aadhaar & PAN-verified candidate vault and employer talent cloud',
  manifest: '/manifest.json',
  icons: { icon: '/icon-192.png', apple: '/icon-192.png' },
};

export const viewport: Viewport = { themeColor: '#141b2d', width: 'device-width', initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PwaRegister />
        {children}
      </body>
    </html>
  );
}
