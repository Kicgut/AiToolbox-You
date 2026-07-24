import { createRouter, createWebHistory } from 'vue-router';
import NotFoundView from '../views/NotFoundView.vue';
import OverviewView from '../views/OverviewView.vue';
import SessionCenterView from '../views/SessionCenterView.vue';

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: OverviewView },
    { path: '/sessions', component: SessionCenterView },
    { path: '/:pathMatch(.*)*', component: NotFoundView }
  ]
});
