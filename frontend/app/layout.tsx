import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI Job Application Assistant',
  description: 'AI-powered CV and job description matching with skill-gap analysis and tailored application guidance.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
