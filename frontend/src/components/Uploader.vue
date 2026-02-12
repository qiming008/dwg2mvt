<template>
  <form @submit.prevent="onSubmit" class="uploader-form">
    <label class="uploader-label-btn" :title="file ? file.name : '点击选择文件'">
      <span class="filename-span">{{ file ? file.name : '选择 DWG 文件' }}</span>
      <input
        type="file"
        accept=".dwg"
        @change="onFileChange"
        :disabled="loading"
        class="uploader-input"
      />
    </label>
    <button type="submit" :disabled="loading || !file" class="uploader-submit-btn">
      {{ loading ? '处理中…' : '上传切片' }}
    </button>
  </form>

  <!-- Progress Modal -->
  <div v-if="loading" class="modal-overlay">
    <div class="modal-content">
      <h3>正在处理切片...</h3>
      
      <div class="progress-wrapper">
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <div class="progress-text">{{ progress }}% - {{ progressMsg }}</div>
      </div>
      
      <div v-if="showDetails" class="logs-container">
        <div v-for="(log, idx) in logs" :key="idx" class="log-item">
            {{ log }}
        </div>
      </div>

      <div class="modal-footer">
        <button type="button" @click="showDetails = !showDetails" class="detail-btn">
            {{ showDetails ? '收起详细' : '详细信息' }}
         </button>
        <button type="button" @click="cancelUpload" class="cancel-btn">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { ConvertResult } from '../types'

const props = defineProps<{
  apiBase: string
}>()

const emit = defineEmits<{
  (e: 'convert', res: ConvertResult): void
  (e: 'error', msg: string): void
}>()

const loading = ref(false)
const progress = ref(0)
const progressMsg = ref('')
const file = ref<File | null>(null)
const showDetails = ref(false)
const logs = ref<string[]>([])
const currentJobId = ref<string | null>(null)
const xhr = ref<XMLHttpRequest | null>(null)

const onFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  file.value = target.files?.[0] ?? null
}

const addLog = (msg: string) => {
  if (!msg) return
  // Avoid duplicate consecutive logs
  const last = logs.value[logs.value.length - 1]
  if (last !== msg) {
    logs.value.push(msg)
  }
}

const cancelUpload = () => {
    if (xhr.value) {
        xhr.value.abort()
        xhr.value = null
    }
    loading.value = false
    currentJobId.value = null
    logs.value = []
    emit('error', '已取消上传')
}

const pollStatus = async (jobId: string) => {
  if (!loading.value) return // Stop polling if cancelled
  
  const poll = async () => {
    if (!loading.value || currentJobId.value !== jobId) return

    try {
      const r = await fetch(`${props.apiBase}/status/${jobId}`)
      if (!r.ok) {
          if (loading.value) setTimeout(poll, 2000)
          return
      }
      
      const res = await r.json() as ConvertResult
      progress.value = res.progress || 0
      progressMsg.value = res.message || ''
      addLog(res.message || '')

      if (res.status === 'done') {
        loading.value = false
        emit('convert', res)
        return
      }
      
      if (res.status === 'error') {
        loading.value = false
        emit('error', res.message || '转换失败')
        return
      }
      
      // Continue polling
      setTimeout(poll, 1000)
    } catch (err) {
      console.error(err)
      // Retry on network error
      if (loading.value) setTimeout(poll, 2000)
    }
  }
  poll()
}

const onSubmit = async () => {
  if (!file.value || !file.value.name.toLowerCase().endsWith('.dwg')) {
    emit('error', '请选择 .dwg 文件')
    return
  }
  
  loading.value = true
  progress.value = 0
  progressMsg.value = '正在上传...'
  logs.value = ['开始上传...']
  showDetails.value = false
  emit('error', '')
  
  try {
    const form = new FormData()
    form.append('file', file.value)
    
    // Use XMLHttpRequest for upload progress
    const req = new XMLHttpRequest()
    xhr.value = req
    
    req.open('POST', `${props.apiBase}/convert`)
    
    req.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const percent = Math.round((e.loaded / e.total) * 100)
        progress.value = percent
        progressMsg.value = `正在上传... ${percent}%`
      }
    }
    
    req.onload = () => {
        xhr.value = null
        if (req.status >= 200 && req.status < 300) {
            try {
                const res = JSON.parse(req.responseText) as ConvertResult
                if (res.status === 'error') {
                    loading.value = false
                    emit('error', res.message || '转换失败')
                    return
                }
                
                // Upload done, start polling
                addLog('上传完成，等待处理...')
                progress.value = 0
                progressMsg.value = '准备转换...'
                currentJobId.value = res.job_id
                pollStatus(res.job_id)
            } catch (e) {
                loading.value = false
                emit('error', '响应解析失败')
            }
        } else {
            loading.value = false
            let msg = `请求失败 ${req.status}`
            try {
                const err = JSON.parse(req.responseText)
                msg = err.detail?.msg || err.detail || err.message || msg
            } catch {}
            emit('error', msg)
        }
    }
    
    req.onerror = () => {
        xhr.value = null
        loading.value = false
        emit('error', '网络错误')
    }
    
    req.onabort = () => {
        xhr.value = null
    }

    req.send(form)
    
  } catch (err) {
    loading.value = false
    emit('error', err instanceof Error ? err.message : '未知错误')
  }
}
</script>



<style scoped>
.uploader-form {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 10px;
}

.uploader-label-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  border: 1px solid #ccc;
  border-radius: 4px;
  cursor: pointer;
  background-color: white;
  min-width: 150px;
  max-width: 250px;
  height: 36px;
  box-sizing: border-box;
  transition: all 0.2s;
}

.uploader-label-btn:hover {
  border-color: #3b82f6;
  color: #3b82f6;
}

.filename-span {
  font-size: 14px;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.uploader-input {
  display: none;
}

.uploader-submit-btn {
  padding: 0 16px;
  height: 36px;
  background-color: #3b82f6;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.3s;
  white-space: nowrap;
}

.uploader-submit-btn:disabled {
  background-color: #93c5fd;
  cursor: not-allowed;
}

.uploader-submit-btn:hover:not(:disabled) {
  background-color: #2563eb;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}
.modal-content {
  background: white;
  padding: 20px;
  border-radius: 8px;
  width: 90%;
  max-width: 500px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  display: flex;
  flex-direction: column;
  gap: 15px;
}
.modal-content h3 {
  margin: 0 0 10px 0;
  text-align: center;
  color: #333;
}
.modal-actions {
  display: flex;
  justify-content: center;
}
.detail-btn {
  background: none;
  border: none;
  color: #3b82f6;
  cursor: pointer;
  font-size: 14px;
  text-decoration: underline;
}
.logs-container {
  max-height: 200px;
  overflow-y: auto;
  background: #f9f9f9;
  border: 1px solid #eee;
  padding: 10px;
  border-radius: 4px;
  font-size: 12px;
  color: #666;
}
.log-item {
  margin-bottom: 4px;
  border-bottom: 1px dashed #eee;
  padding-bottom: 2px;
}
.modal-footer {
  display: flex;
  justify-content: center;
  margin-top: 10px;
}
.cancel-btn {
  padding: 8px 24px;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  color: #666;
  transition: all 0.2s;
}
.cancel-btn:hover {
  background: #f5f5f5;
  border-color: #ccc;
  color: #333;
}

/* Progress Bar reused */
.progress-wrapper {
  width: 100%;
}
.progress-bar-bg {
  width: 100%;
  height: 10px;
  background-color: #f0f0f0;
  border-radius: 5px;
  overflow: hidden;
  border: 1px solid #eee;
}
.progress-bar-fill {
  height: 100%;
  background-color: #3b82f6;
  transition: width 0.3s ease;
  background-image: linear-gradient(
    45deg,
    rgba(255, 255, 255, 0.15) 25%,
    transparent 25%,
    transparent 50%,
    rgba(255, 255, 255, 0.15) 50%,
    rgba(255, 255, 255, 0.15) 75%,
    transparent 75%,
    transparent
  );
  background-size: 1rem 1rem;
  animation: progress-bar-stripes 1s linear infinite;
}

@keyframes progress-bar-stripes {
  from {
    background-position: 1rem 0;
  }
  to {
    background-position: 0 0;
  }
}
.progress-text {
  font-size: 13px;
  color: #555;
  text-align: center;
  margin-top: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>