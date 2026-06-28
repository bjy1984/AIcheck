import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import type { App } from 'vue'
import { Layout } from '@/utils/routerHelper'
import { NO_RESET_WHITE_LIST } from '@/constants'

const AICheckStaticLayout = () => import('@/layout/AICheckStaticLayout.vue')
const AdminOverview = () => import('@/views/AICheck/AdminOverview.vue')
const KnowledgeOverview = () => import('@/views/AICheck/KnowledgeOverview.vue')

export const constantRouterMap: AppRouteRecordRaw[] = [
  {
    path: '/',
    component: Layout,
    redirect: '/workbench/inspection',
    name: 'Root',
    meta: {
      hidden: true
    }
  },
  {
    path: '/redirect',
    component: Layout,
    name: 'RedirectWrap',
    children: [
      {
        path: '/redirect/:path(.*)',
        name: 'Redirect',
        component: () => import('@/views/Redirect/Redirect.vue'),
        meta: {}
      }
    ],
    meta: {
      hidden: true,
      noTagsView: true
    }
  },
  {
    path: '/login',
    component: () => import('@/views/Login/Login.vue'),
    name: 'Login',
    meta: {
      hidden: true,
      title: '登录',
      noTagsView: true
    }
  },
  {
    path: '/404',
    component: () => import('@/views/Error/404.vue'),
    name: 'NoFind',
    meta: {
      hidden: true,
      title: '404',
      noTagsView: true
    }
  }
]

export const asyncRouterMap: AppRouteRecordRaw[] = [
  {
    path: '/workbench',
    component: AICheckStaticLayout,
    redirect: '/workbench/inspection',
    name: 'Workbench',
    meta: {
      title: '业务工作台',
      icon: 'vi-ep:monitor',
      alwaysShow: true,
      roles: ['inspection', 'contractor', 'ndt', 'owner']
    },
    children: [
      {
        path: 'generic',
        component: () => import('@/views/AICheck/GenericReviewWorkbench.vue'),
        name: 'GenericReviewWorkbench',
        meta: {
          title: '通用资料审查',
          icon: 'vi-ep:collection',
          noCache: true,
          roles: ['admin', 'inspection', 'contractor', 'owner']
        }
      },
      {
        path: 'inspection',
        component: () => import('@/views/AICheck/Workbench.vue'),
        name: 'InspectionWorkbench',
        meta: {
          title: '监检工作台',
          icon: 'vi-ep:checked',
          noCache: true,
          affix: true,
          roles: ['inspection']
        }
      },
      {
        path: 'contractor',
        component: () => import('@/views/AICheck/Workbench.vue'),
        name: 'ContractorWorkbench',
        meta: {
          title: '施工方工作台',
          icon: 'vi-ep:upload-filled',
          noCache: true,
          roles: ['contractor']
        }
      },
      {
        path: 'ndt',
        component: () => import('@/views/AICheck/Workbench.vue'),
        name: 'NdtWorkbench',
        meta: {
          title: '无损检测工作台',
          icon: 'vi-ep:data-analysis',
          noCache: true,
          roles: ['ndt']
        }
      },
      {
        path: 'owner',
        component: () => import('@/views/AICheck/Workbench.vue'),
        name: 'OwnerWorkbench',
        meta: {
          title: '建设方工作台',
          icon: 'vi-ep:view',
          noCache: true,
          roles: ['owner']
        }
      }
    ]
  },
  {
    path: '/admin',
    component: AICheckStaticLayout,
    redirect: '/admin/overview',
    name: 'AICheckAdmin',
    meta: {
      title: '管理后台',
      icon: 'vi-ep:setting',
      alwaysShow: true,
      roles: ['admin']
    },
    children: [
      {
        path: 'overview',
        component: AdminOverview,
        name: 'AdminOverview',
        meta: {
          title: '项目与权限配置',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'projects',
        component: AdminOverview,
        name: 'AdminProjects',
        meta: {
          title: '项目清单',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'org',
        component: AdminOverview,
        name: 'AdminOrg',
        meta: {
          title: '组织用户',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'business-packs',
        component: AdminOverview,
        name: 'AdminBusinessPacks',
        meta: {
          title: '业务包管理',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'permission',
        component: AdminOverview,
        name: 'AdminPermission',
        meta: {
          title: '权限与节点',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'rules',
        component: AdminOverview,
        name: 'AdminRules',
        meta: {
          title: '规则与流程',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'fine-config',
        component: AdminOverview,
        name: 'AdminFineConfig',
        meta: {
          title: '细项配置',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'integration',
        component: AdminOverview,
        name: 'AdminIntegration',
        meta: {
          title: '联调清单',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'audit',
        component: AdminOverview,
        name: 'AdminAudit',
        meta: {
          title: '审计日志',
          noCache: true,
          roles: ['admin']
        }
      }
    ]
  },
  {
    path: '/knowledge',
    component: AICheckStaticLayout,
    redirect: '/knowledge/overview',
    name: 'Knowledge',
    meta: {
      title: 'AI 知识库',
      icon: 'vi-ep:collection',
      alwaysShow: true,
      roles: ['admin']
    },
    children: [
      {
        path: 'overview',
        component: KnowledgeOverview,
        name: 'KnowledgeOverview',
        meta: {
          title: '知识库管理',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'sources',
        component: KnowledgeOverview,
        name: 'KnowledgeSources',
        meta: {
          title: '知识源管理',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'files',
        component: KnowledgeOverview,
        name: 'KnowledgeFiles',
        meta: {
          title: '项目文件库',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'tasks',
        component: KnowledgeOverview,
        name: 'KnowledgeTasks',
        meta: {
          title: '任务中心',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'rules',
        component: KnowledgeOverview,
        name: 'KnowledgeRules',
        meta: {
          title: '规则配置',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'retrieval',
        component: KnowledgeOverview,
        name: 'KnowledgeRetrieval',
        meta: {
          title: '检索测试',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'reasoning',
        component: KnowledgeOverview,
        name: 'KnowledgeReasoning',
        meta: {
          title: '推理日志',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'compare',
        component: KnowledgeOverview,
        name: 'KnowledgeCompare',
        meta: {
          title: '多模型对比',
          noCache: true,
          roles: ['admin']
        }
      },
      {
        path: 'config',
        component: KnowledgeOverview,
        name: 'KnowledgeConfig',
        meta: {
          title: '配置审计',
          noCache: true,
          roles: ['admin']
        }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  strict: true,
  routes: constantRouterMap as RouteRecordRaw[],
  scrollBehavior: () => ({ left: 0, top: 0 })
})

export const resetRouter = (): void => {
  router.getRoutes().forEach((route) => {
    const { name } = route
    if (name && !NO_RESET_WHITE_LIST.includes(name as string)) {
      router.hasRoute(name) && router.removeRoute(name)
    }
  })
}

export const setupRouter = (app: App<Element>) => {
  app.use(router)
}

export default router
