import './globals.css';

export const metadata = {
  title: 'Agentic URL Shortener',
  description: 'Interactive demo for URL shortening and agentic SDLC orchestration',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
