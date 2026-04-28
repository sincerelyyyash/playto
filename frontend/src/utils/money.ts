/** Integer-safe display: paise is the source of truth (assignment). */

export function formatPaiseLine(paise: number): string {
  const rupees = Math.floor(paise / 100)
  const remainder = paise % 100
  const rupeesStr = rupees.toLocaleString('en-IN')
  const paiseStr = paise.toLocaleString('en-IN')
  return `₹${rupeesStr}.${remainder.toString().padStart(2, '0')} (${paiseStr} paise)`
}
