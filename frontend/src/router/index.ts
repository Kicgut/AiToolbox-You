import { createRouter, createWebHistory } from 'vue-router';
import NotFoundView from '../views/NotFoundView.vue';
import OverviewView from '../views/OverviewView.vue';
import SessionCenterView from '../views/SessionCenterView.vue';
import StatisticsView from '../views/StatisticsView.vue';
import TrafficView from '../views/TrafficView.vue';
import RunCenterView from '../views/RunCenterView.vue';
import SettingsView from '../views/SettingsView.vue';

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: OverviewView },
    { path: '/sessions', component: SessionCenterView },
    { path: '/runs', component: RunCenterView },
    { path: '/statistics', component: StatisticsView },
    { path: '/traffic', component: TrafficView },
    { path: '/settings', component: SettingsView },
    { path: '/:pathMatch(.*)*', component: NotFoundView }
  ]
});
