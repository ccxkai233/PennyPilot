export const ACCOUNT_ROLE_GROUPS = Object.freeze([
  { role: 'cash', label: '现金账户', shortLabel: '现金', icon: '¥' },
  { role: 'investment', label: '投资账户', shortLabel: '投资', icon: '↗' },
  { role: 'liability', label: '负债账户', shortLabel: '负债', icon: '欠' },
])

function normalizedRole(role) {
  const value = String(role || 'cash')
  return ACCOUNT_ROLE_GROUPS.some((group) => group.role === value) ? value : 'cash'
}

function accountOrder(left, right) {
  const sortDifference = Number(left.sort_order ?? left.sort ?? 0) - Number(right.sort_order ?? right.sort ?? 0)
  if (sortDifference) return sortDifference
  return Number(left.id ?? 0) - Number(right.id ?? 0)
}

export function groupAccounts(accounts = []) {
  return ACCOUNT_ROLE_GROUPS.map((group) => ({
    ...group,
    items: accounts
      .filter((account) => normalizedRole(account.account_role) === group.role)
      .slice()
      .sort(accountOrder),
  })).filter((group) => group.items.length)
}

export function sortAccounts(accounts = []) {
  return groupAccounts(accounts).flatMap((group) => group.items)
}
