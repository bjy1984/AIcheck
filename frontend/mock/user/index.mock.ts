import { SUCCESS_CODE } from '@/constants'

const timeout = 1000

const List: {
  id: string
  username: string
  password: string
  role: string
  roleId: string
  roleLabel: string
  displayName: string
  orgUnitName: string
  defaultPath: string
  permissions: string | string[]
}[] = [
  {
    id: 'USER-INSPECTION-001',
    username: 'inspection',
    password: 'inspection',
    role: 'inspection',
    roleId: '2',
    roleLabel: '监检人员',
    displayName: '张工',
    orgUnitName: '省特检院一部',
    defaultPath: '/workbench/inspection',
    permissions: ['inspection:default']
  },
  {
    id: 'USER-CONTRACTOR-001',
    username: 'contractor',
    password: 'contractor',
    role: 'contractor',
    roleId: '3',
    roleLabel: '施工方',
    displayName: '李工',
    orgUnitName: '中石化安装有限公司',
    defaultPath: '/workbench/contractor',
    permissions: ['contractor:default']
  },
  {
    id: 'USER-NDT-001',
    username: 'ndt',
    password: 'ndt',
    role: 'ndt',
    roleId: '4',
    roleLabel: '无损检测',
    displayName: '王工',
    orgUnitName: '华测检测有限公司',
    defaultPath: '/workbench/ndt',
    permissions: ['ndt:default']
  },
  {
    id: 'USER-OWNER-001',
    username: 'owner',
    password: 'owner',
    role: 'owner',
    roleId: '5',
    roleLabel: '建设方',
    displayName: '赵经理',
    orgUnitName: '华东管网建设公司',
    defaultPath: '/workbench/owner',
    permissions: ['owner:default']
  },
  {
    id: 'USER-ADMIN-001',
    username: 'admin',
    password: 'admin',
    role: 'admin',
    roleId: '1',
    roleLabel: '系统管理员',
    displayName: '系统管理员',
    orgUnitName: '省特检院平台组',
    defaultPath: '/admin/overview',
    permissions: ['*.*.*']
  },
  {
    id: 'USER-FDE-001',
    username: 'fde',
    password: 'fde',
    role: 'fde',
    roleId: '6',
    roleLabel: 'FDE 工程师',
    displayName: 'FDE 工程师',
    orgUnitName: 'AI 交付治理组',
    defaultPath: '/fde/dashboard',
    permissions: ['fde:default']
  },
  {
    id: 'USER-TEST-001',
    username: 'test',
    password: 'test',
    role: 'test',
    roleId: '2',
    roleLabel: '测试用户',
    displayName: '测试用户',
    orgUnitName: '联调测试组',
    defaultPath: '/workbench/inspection',
    permissions: ['example:dialog:create', 'example:dialog:delete']
  }
]

export default [
  // 列表接口
  {
    url: '/mock/user/list',
    method: 'get',
    response: ({ query }) => {
      const { username, pageIndex, pageSize } = query

      const mockList = List.filter((item) => {
        if (username && item.username.indexOf(username) < 0) return false
        return true
      })
      const pageList = mockList.filter(
        (_, index) => index < pageSize * pageIndex && index >= pageSize * (pageIndex - 1)
      )

      return {
        code: SUCCESS_CODE,
        data: {
          total: mockList.length,
          list: pageList
        }
      }
    }
  },
  // 登录接口
  {
    url: '/mock/user/login',
    method: 'post',
    timeout,
    response: ({ body }) => {
      const data = body
      let hasUser = false
      for (const user of List) {
        if (user.username === data.username && user.password === data.password) {
          hasUser = true
          const { password, ...safeUser } = user
          return {
            code: SUCCESS_CODE,
            data: safeUser
          }
        }
      }
      if (!hasUser) {
        return {
          code: 500,
          message: '账号或密码错误'
        }
      }
    }
  },
  // 退出接口
  {
    url: '/mock/user/loginOut',
    method: 'get',
    timeout,
    response: () => {
      return {
        code: SUCCESS_CODE,
        data: null
      }
    }
  }
]
