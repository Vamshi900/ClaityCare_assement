import type { ReactNode } from 'react'

interface LayoutProps {
  left: ReactNode
  right: ReactNode
}

export default function Layout({ left, right }: LayoutProps) {
  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-3 flex-shrink-0">
        <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center">
          <span className="text-white font-bold text-sm">O</span>
        </div>
        <h1 className="text-lg font-bold text-gray-800">Oscar Guidelines Explorer</h1>
      </header>

      {/* Body */}
      <div className="flex flex-1 min-h-0">
        {/* Left Panel */}
        <aside className="w-96 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
          {left}
        </aside>

        {/* Right Panel */}
        <main className="flex-1 flex flex-col min-w-0">
          {right}
        </main>
      </div>
    </div>
  )
}
