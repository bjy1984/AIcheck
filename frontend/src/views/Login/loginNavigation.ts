import { isNavigationFailure } from 'vue-router'
import type { NavigationFailure } from 'vue-router'

export const didLoginNavigationComplete = (
  result: void | NavigationFailure,
  currentPath: string
): boolean => {
  return !isNavigationFailure(result) && currentPath !== '/login'
}
