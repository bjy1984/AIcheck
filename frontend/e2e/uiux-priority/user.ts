const user = {
  getUserInfo: { username: 'UI verification', role: 'fde', permissions: [] },
  getToken: '',
  getTokenKey: 'Authorization',
  logoutConfirm() {}
}
export const useUserStore = () => user
export const useUserStoreWithOut = () => user
