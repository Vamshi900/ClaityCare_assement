interface OperatorBadgeProps {
  operator: 'AND' | 'OR'
}

export default function OperatorBadge({ operator }: OperatorBadgeProps) {
  const colors =
    operator === 'AND'
      ? 'bg-blue-100 text-blue-700 border-blue-300'
      : 'bg-amber-100 text-amber-700 border-amber-300'

  return (
    <span
      className={`text-xs font-bold px-2 py-0.5 rounded border ${colors} select-none`}
    >
      {operator}
    </span>
  )
}
