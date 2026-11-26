import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'VerifyHire — Verified Resume Registry',
  description: 'AI-native, Aadhaar & PAN-verified candidate vault and employer talent cloud',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
