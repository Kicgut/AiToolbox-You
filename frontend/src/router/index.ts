import { createRouter, createWebHistory } from 'vue-router';
import NotFoundView from '../views/NotFoundView.vue';
import OverviewView from '../views/OverviewView.vue';
import SessionCenterView from '../views/SessionCenterView.vue';
import StatisticsView from '../views/StatisticsView.vue';

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: OverviewView },
    { path: '/sessions', component: SessionCenterView },
    { path: '/statistics', component: StatisticsView },
    { path: '/:pathMatch(.*)*', component: NotFoundView }
  ]
});
