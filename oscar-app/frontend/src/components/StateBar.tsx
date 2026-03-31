interface StateBarProps {
  status: string
}

const STAGES = [
  { key: 'discovered', label: 'DISC' },
  { key: 'downloaded', label: 'DOWN' },
  { key: 'extracted', label: 'EXTR' },
  { key: 'validated', label: 'VALID' },
] as const

const STATUS_TO_STAGE: Record<string, { index: number; failed: boolean; inProgress: boolean }> = {
  discovered:        { index: 0, failed: false, inProgress: false },
  downloading:       { index: 1, failed: false, inProgress: true },
  downloaded:        { index: 1, failed: false, inProgress: false },
  download_failed:   { index: 1, failed: true,  inProgress: false },
  extracting:        { index: 2, failed: false, inProgress: true },
  extracted:         { index: 2, failed: false, inProgress: false },
  extraction_failed: { index: 2, failed: true,  inProgress: false },
  validated:         { index: 3, failed: false, inProgress: false },
}

export default function StateBar({ status }: StateBarProps) {
  const info = STATUS_TO_STAGE[status] || { index: 0, failed: false, inProgress: false }

  return (
    <div className="flex items-center gap-0 my-3">
      {STAGES.map((stage, i) => {
        const isCompleted = i < info.index
        const isCurrent = i === info.index
        const isFailed = isCurrent && info.failed
        const isPulsing = isCurrent && info.inProgress
        const isFuture = i > info.index

        let circleClasses = 'w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 '
        if (isFailed) {
          circleClasses += 'bg-red-500 text-white'
        } else if (isCompleted) {
          circleClasses += 'bg-green-500 text-white'
        } else if (isCurrent && !isFailed) {
          circleClasses += 'bg-blue-500 text-white'
          if (isPulsing) circleClasses += ' animate-pulse'
        } else {
          circleClasses += 'border-2 border-gray-300 text-gray-300'
        }

        let lineClasses = 'flex-shrink-0 h-0.5 w-6 '
        if (i < info.index) {
          lineClasses += 'bg-green-400'
        } else if (i === info.index && !isFuture) {
          lineClasses += 'bg-blue-300'
        } else {
          lineClasses += 'bg-gray-200'
        }

        return (
          <div key={stage.key} className="flex items-center">
            {i > 0 && <div className={lineClasses} />}
            <div className="flex flex-col items-center">
              <div className={circleClasses}>
                {isFailed ? (
                  <span>X</span>
                ) : isCompleted || (isCurrent && !isFailed) ? (
                  <span>{'\u2022'}</span>
                ) : (
                  <span>{'\u25CB'}</span>
                )}
              </div>
              <span className={`text-[9px] mt-0.5 font-medium ${
                isFailed ? 'text-red-500' :
                isCompleted ? 'text-green-600' :
                isCurrent ? 'text-blue-600' :
                'text-gray-400'
              }`}>
                {stage.label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
