<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useUsersStore } from '@/stores/users'
import { useFeatureFlag } from '@/composables/feature'

defineOptions({ name: 'UserList' })
const props = defineProps<{ teamId: string }>()
const emit = defineEmits(['select'])
const model = defineModel<string>('selectedId')
defineSlots<{ default: (props: { active: boolean }) => any }>()

const route = useRoute()
const router = useRouter()
const usersStore = useUsersStore()
const userRefs = storeToRefs(usersStore)
const users = computed(() => [])
</script>

<template>
  <UserCard />
  <slot name="default" />
</template>
