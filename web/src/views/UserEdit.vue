<template>
  <el-card class="page-card">
    <template #header>
      <div class="page-header">
        <div class="page-title">{{ isEdit ? '编辑用户' : '添加用户' }}</div>
        <div class="page-actions">
          <el-button v-if="isEdit && canRun" type="primary" plain @click="goPreauthorization">预授权</el-button>
          <el-button @click="goBack">返回</el-button>
        </div>
      </div>
    </template>

    <el-form
      :model="form"
      :label-width="isMobile ? 'auto' : '120px'"
      :label-position="isMobile ? 'top' : 'right'"
      v-loading="loading"
    >
      <el-tabs v-model="activeTab">
        <el-tab-pane label="基本信息" name="basic">
          <el-form-item label="账号">
            <el-input v-model="form.phone" placeholder="请输入工学云账号" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" type="password" show-password autocomplete="new-password" :placeholder="passwordPlaceholder" />
          </el-form-item>
          <el-form-item v-if="!isEdit" label="账号信息">
            <div class="account-prefill-controls">
              <el-button type="primary" :disabled="!form.phone.trim() || !form.password.trim() || accountInfoLoading" :loading="accountInfoLoading" @click="fetchNewAccountInfo">获取账号信息</el-button>
              <span class="account-prefill-hint">{{ accountInfoFetched && !accountInfoReady ? '位置未完整：启用自动打卡需补全有效地址和经纬度，或关闭自动打卡' : '获取后核对摘要即可保存，其余选项使用默认值' }}</span>
            </div>
          </el-form-item>
          <el-alert
            v-if="!isEdit && (accountInfoProfile || accountInfoState === 'expired')"
            :title="accountInfoState === 'expired' ? '账号凭据已变更，之前获取的信息已过期' : `账号信息摘要 · ${accountInfoReady ? '位置已完整读取' : '位置未完整读取'}`"
            :description="accountInfoSummary"
            :type="accountInfoState === 'expired' ? 'warning' : (accountInfoReady ? 'success' : 'info')"
            :closable="false"
            show-icon
            class="account-prefill-summary"
          />
          <el-alert
            v-if="!isEdit && accountInfoWarnings.length"
            :title="accountInfoWarnings.join('；')"
            type="warning"
            :closable="false"
            show-icon
            class="account-prefill-summary"
          />
          <el-form-item label="备注">
            <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="例如：张三/研发部/某项目（支持搜索）" />
          </el-form-item>
          <el-form-item label="启用打卡">
            <el-switch v-model="form.enable_clockin" active-text="开启自动任务" />
          </el-form-item>
        </el-tab-pane>

        <el-tab-pane label="打卡设置" name="clockin">
          <ClockInPhotos
            v-model="form.clockIn.photoEnabled"
            :endpoint="isEdit ? `/users/${route.params.id}/clock-in/photos` : ''"
            :client="http"
            :disabled="loading || saving"
          />
          <el-alert title="搜索地址可自动获取经纬度和地址，也可在经纬度查询页手动核对" type="info" :closable="false" style="margin-bottom: 15px;" />
          
          <el-form-item label="详细地址">
            <div class="place-row">
              <el-input
                class="place-input"
                v-model="searchQuery"
                placeholder="例如：湖南省 · 长沙市 · 岳麓区 · 在麓谷企业广场附近"
                @keyup.enter="searchPlace"
              />
              <div class="place-actions">
                <el-button type="primary" @click="searchPlace">搜索</el-button>
                <el-button :disabled="!isEdit" :loading="accountRefreshLoading" @click="refreshAccountLocation">获取账号信息/上班位置</el-button>
                <el-button :disabled="!isEdit" :loading="addrFillLoading" @click="fillFromAccountAddress">读取账号地址候选</el-button>
              </div>
            </div>
          </el-form-item>

          <div class="map external-map">
            <iframe :src="mapDisplayUrl" title="经纬度查询地图" loading="lazy" referrerpolicy="no-referrer"></iframe>
          </div>
          <el-alert
            v-if="accountLocationMessage || accountLocation"
            :title="accountLocation ? `账号位置候选 · 来源：${accountLocation.source || '来源未说明'}` : (accountLocationMessage || '未获取到账号位置候选')"
            :description="accountLocation ? (accountLocationMessage || '候选仅供核对，不会自动写入打卡位置；可编辑后手动应用。缺少经纬度时不可应用。') : accountLocationMessage"
            :type="accountLocation ? 'info' : 'warning'"
            :closable="false"
            show-icon
            class="account-location-alert"
          />
          <div v-if="accountLocation" class="account-location-candidate">
            <el-form-item label="候选地址"><el-input v-model="accountLocation.address" /></el-form-item>
            <el-row>
              <el-col :xs="24" :sm="12"><el-form-item label="候选纬度"><el-input v-model="accountLocation.latitude" /></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="候选经度"><el-input v-model="accountLocation.longitude" /></el-form-item></el-col>
            </el-row>
            <el-row>
              <el-col :xs="24" :sm="8"><el-form-item label="候选省份"><el-input v-model="accountLocation.province" /></el-form-item></el-col>
              <el-col :xs="24" :sm="8"><el-form-item label="候选城市"><el-input v-model="accountLocation.city" /></el-form-item></el-col>
              <el-col :xs="24" :sm="8"><el-form-item label="候选区域"><el-input v-model="accountLocation.area" /></el-form-item></el-col>
            </el-row>
            <el-button type="warning" :disabled="!canApplyAccountLocation" @click="applyAccountLocation">应用候选位置到打卡设置</el-button>
          </div>

          <el-form-item label="上班打卡">
            <el-time-select v-model="form.clockIn.schedule.startTime" start="00:00" step="00:01" end="23:59" />
          </el-form-item>
          <el-form-item label="下班打卡">
            <el-time-select v-model="form.clockIn.schedule.endTime" start="00:00" step="00:01" end="23:59" />
          </el-form-item>
          <el-form-item label="打卡开始日期">
            <el-date-picker v-model="form.clockIn.schedule.startDate" type="date" value-format="YYYY-MM-DD" placeholder="不设则从当前起算" />
          </el-form-item>
          <el-form-item label="打卡结束日期">
            <el-date-picker v-model="form.clockIn.schedule.endDate" type="date" value-format="YYYY-MM-DD" placeholder="可选，包含结束日" />
          </el-form-item>
          <el-form-item label="跳过节假日">
            <el-switch v-model="form.clockIn.schedule.skipHolidays" active-text="不安排节假日打卡" />
          </el-form-item>
          <el-form-item v-if="isEdit" label="补卡日期">
            <div class="clockin-backfill">
              <div class="clockin-backfill-row">
                <el-select v-model="clockInMakeupType" class="clockin-type-select" placeholder="补卡类型" @change="syncClockInTargetFromOptions">
                  <el-option label="上班" value="START" />
                  <el-option label="下班" value="END" />
                </el-select>
                <el-select v-model="clockInTargetDates" :loading="clockInPeriodLoading" multiple collapse-tags collapse-tags-tooltip filterable placeholder="选择待补日期">
                  <el-option v-for="item in filteredClockInPeriodOptions" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-button :loading="clockInPeriodLoading" @click="loadClockInMissingDays">刷新缺卡</el-button>
                <el-button type="warning" :loading="clockInMakeupLoading" :disabled="!clockInTargetDates.length" @click="makeupClockIn">补选中</el-button>
                <el-button type="danger" :loading="clockInMakeupAllLoading" :disabled="!filteredClockInPeriodOptions.length" @click="makeupAllClockIn">全部待补</el-button>
              </div>
              <el-progress
                v-if="clockInMakeupAllLoading || clockInMakeupAllPercent > 0"
                class="clockin-backfill-progress"
                :percentage="clockInMakeupAllPercent"
                :status="clockInMakeupAllPercent >= 100 ? 'success' : undefined"
              />
              <div class="clockin-backfill-hint">
                已获取 {{ clockInRecordCount }} 条打卡记录，{{ clockInMakeupTypeLabel }}待补 {{ filteredClockInPeriodOptions.length }} 天，已选 {{ clockInTargetDates.length }} 天
              </div>
            </div>
          </el-form-item>
          <el-form-item label="打卡周期">
            <el-checkbox-group v-model="form.clockIn.schedule.weekdays" class="week-group">
              <el-checkbox v-for="d in weekdayOptions" :key="d.value" :value="d.value">{{ d.label }}</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item label="有效日历天数">
            <div class="calendar-days-setting">
              <el-input-number v-model="form.clockIn.schedule.totalDays" :min="1" :max="3650" />
              <span>含休息日；与结束日期同时设置时，以较早者为准</span>
            </div>
          </el-form-item>
          <el-row>
            <el-col :xs="24" :sm="12">
              <el-form-item label="纬度">
                <el-input v-model="form.clockIn.location.latitude" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="经度">
                <el-input v-model="form.clockIn.location.longitude" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row>
             <el-col :xs="24" :sm="8">
               <el-form-item label="省份">
                <el-input v-model="form.clockIn.location.province" />
              </el-form-item>
             </el-col>
             <el-col :xs="24" :sm="8">
               <el-form-item label="城市">
                <el-input v-model="form.clockIn.location.city" />
              </el-form-item>
             </el-col>
             <el-col :xs="24" :sm="8">
               <el-form-item label="区域">
                <el-input v-model="form.clockIn.location.area" />
              </el-form-item>
             </el-col>
          </el-row>
        </el-tab-pane>

        <el-tab-pane label="报告设置" name="report">
          <el-divider content-position="left">日报</el-divider>
          <el-form-item label="启用日报">
            <el-switch v-model="form.reportSettings.daily.enabled" />
          </el-form-item>
          <el-form-item v-if="form.reportSettings.daily.enabled" label="提交时间">
            <el-time-select v-model="form.reportSettings.daily.submitTime" start="00:00" step="00:01" end="23:59" />
          </el-form-item>
          <el-form-item v-if="form.reportSettings.daily.enabled" label="提交日(周)">
            <el-checkbox-group v-model="form.reportSettings.daily.submitDays" class="week-group">
              <el-checkbox v-for="d in weekdayOptions" :key="d.value" :value="d.value">{{ d.label }}</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item label="日报字数范围">
            <div class="word-range"><el-input-number v-model="form.reportSettings.daily.minWords" :min="1" :max="10000" /> 至 <el-input-number v-model="form.reportSettings.daily.maxWords" :min="1" :max="10000" /> 字（去除空白后计数）</div>
          </el-form-item>
          <el-form-item label="补交日期">
            <div class="report-backfill">
              <div class="report-backfill-row">
                <el-select v-model="reportTargets.daily" :loading="reportPeriodLoading.daily" filterable placeholder="选择未提交日报日期">
                  <el-option v-for="item in reportPeriodOptions.daily" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-button :loading="reportPeriodLoading.daily" :disabled="!isEdit || !isReportEnabled('daily') || !!reportMakeupAllLoading" @click="loadReportPeriodOptions('daily')">刷新待补</el-button>
                <el-button type="danger" :loading="reportMakeupAllLoading === 'daily'" :disabled="!isEdit || !isReportEnabled('daily') || !!reportRunLoading || !!reportActionLoading || (!!reportMakeupAllLoading && reportMakeupAllLoading !== 'daily') || !reportPendingCount('daily')" @click="makeupAllReports('daily')">补全部日报</el-button>
              </div>
              <el-progress
                v-if="reportMakeupAllInProgress('daily')"
                class="report-backfill-progress"
                :percentage="reportMakeupAllPercent"
                :status="reportMakeupAllPercent >= 100 ? 'success' : undefined"
              />
              <div class="report-backfill-hint">{{ isReportEnabled('daily') ? `日报待补 ${reportPendingCount('daily')} 个周期` : '日报未开启，不获取待补周期' }}</div>
            </div>
          </el-form-item>
          <el-form-item label="日报预览">
            <div class="report-preview">
              <div class="report-preview-meta">
                <div>字数：{{ dailyCount }} / {{ form.reportSettings.daily.minWords }}–{{ form.reportSettings.daily.maxWords }}</div>
                <div class="report-preview-actions">
                  <el-button size="small" :disabled="!isEdit || !isReportEnabled('daily') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.daily" :loading="reportActionLoading === 'daily_generate'" @click="generateReport('daily')">
                    AI生成日报
                  </el-button>
                  <el-button
                    size="small"
                    type="primary"
                    :disabled="!isEdit || !isReportEnabled('daily') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.daily || !String(reportPreview.daily || '').trim()"
                    :loading="reportActionLoading === 'daily_submit'"
                    @click="submitReport('daily')"
                  >
                    提交日报
                  </el-button>
                  <el-button
                    size="small"
                    type="success"
                    :disabled="!isEdit || !isReportEnabled('daily') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.daily"
                    :loading="reportRunLoading === 'daily_report'"
                    @click="runReportNow('daily_report')"
                  >
                    立即生成并提交
                  </el-button>
                </div>
              </div>
              <el-input
                v-model="reportPreview.daily"
                type="textarea"
                :rows="6"
                resize="none"
                placeholder="点击 AI生成日报 或手动填写后提交"
              />
            </div>
          </el-form-item>
          
          <el-divider content-position="left">周报</el-divider>
          <el-form-item label="启用周报">
            <el-switch v-model="form.reportSettings.weekly.enabled" />
          </el-form-item>
          <el-form-item label="提交日(周)">
            <el-select v-model="form.reportSettings.weekly.submitTime" placeholder="选择周报提交日">
              <el-option v-for="d in weekdayOptions" :key="d.value" :label="d.label" :value="d.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="周报字数范围">
            <div class="word-range"><el-input-number v-model="form.reportSettings.weekly.minWords" :min="1" :max="10000" /> 至 <el-input-number v-model="form.reportSettings.weekly.maxWords" :min="1" :max="10000" /> 字（去除空白后计数）</div>
          </el-form-item>
          <el-form-item v-if="form.reportSettings.weekly.enabled" label="提交时刻">
            <el-time-select v-model="form.reportSettings.weekly.submitAt" start="00:00" step="00:01" end="23:59" />
          </el-form-item>
          <el-form-item label="补交周">
            <div class="report-backfill">
              <div class="report-backfill-row">
                <el-select v-model="reportTargets.weekly" :loading="reportPeriodLoading.weekly" filterable placeholder="选择未提交周报周期">
                  <el-option v-for="item in reportPeriodOptions.weekly" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-button :loading="reportPeriodLoading.weekly" :disabled="!isEdit || !isReportEnabled('weekly') || !!reportMakeupAllLoading" @click="loadReportPeriodOptions('weekly')">刷新待补</el-button>
                <el-button type="danger" :loading="reportMakeupAllLoading === 'weekly'" :disabled="!isEdit || !isReportEnabled('weekly') || !!reportRunLoading || !!reportActionLoading || (!!reportMakeupAllLoading && reportMakeupAllLoading !== 'weekly') || !reportPendingCount('weekly')" @click="makeupAllReports('weekly')">补全部周报</el-button>
              </div>
              <el-progress
                v-if="reportMakeupAllInProgress('weekly')"
                class="report-backfill-progress"
                :percentage="reportMakeupAllPercent"
                :status="reportMakeupAllPercent >= 100 ? 'success' : undefined"
              />
              <div class="report-backfill-hint">{{ isReportEnabled('weekly') ? `周报待补 ${reportPendingCount('weekly')} 个周期` : '周报未开启，不获取待补周期' }}</div>
            </div>
          </el-form-item>
          <el-form-item label="周报预览">
            <div class="report-preview">
              <div class="report-preview-meta">
                <div>字数：{{ weeklyCount }} / {{ form.reportSettings.weekly.minWords }}–{{ form.reportSettings.weekly.maxWords }}</div>
                <div class="report-preview-actions">
                  <el-button size="small" :disabled="!isEdit || !isReportEnabled('weekly') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.weekly" :loading="reportActionLoading === 'weekly_generate'" @click="generateReport('weekly')">
                    AI生成周报
                  </el-button>
                  <el-button
                    size="small"
                    type="primary"
                    :disabled="!isEdit || !isReportEnabled('weekly') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.weekly || !String(reportPreview.weekly || '').trim()"
                    :loading="reportActionLoading === 'weekly_submit'"
                    @click="submitReport('weekly')"
                  >
                    提交周报
                  </el-button>
                  <el-button
                    size="small"
                    type="success"
                    :disabled="!isEdit || !isReportEnabled('weekly') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.weekly"
                    :loading="reportRunLoading === 'weekly_report'"
                    @click="runReportNow('weekly_report')"
                  >
                    立即执行周报
                  </el-button>
                </div>
              </div>
              <el-input v-model="reportPreview.weekly" type="textarea" :rows="6" resize="none" placeholder="点击 AI生成周报 或手动填写后提交" />
            </div>
          </el-form-item>

           <el-divider content-position="left">月报</el-divider>
          <el-form-item label="启用月报">
            <el-switch v-model="form.reportSettings.monthly.enabled" />
          </el-form-item>
          <el-form-item label="提交日(月)">
            <el-select v-model="form.reportSettings.monthly.submitTime" placeholder="选择月报提交日">
              <el-option v-for="day in 31" :key="day" :label="`${day} 号`" :value="day" />
              <el-option label="月末（最后一天）" value="last" />
            </el-select>
          </el-form-item>
          <el-form-item label="月报字数范围">
            <div class="word-range"><el-input-number v-model="form.reportSettings.monthly.minWords" :min="1" :max="10000" /> 至 <el-input-number v-model="form.reportSettings.monthly.maxWords" :min="1" :max="10000" /> 字（去除空白后计数）</div>
          </el-form-item>
          <el-form-item v-if="form.reportSettings.monthly.enabled" label="提交时刻">
            <el-time-select v-model="form.reportSettings.monthly.submitAt" start="00:00" step="00:01" end="23:59" />
          </el-form-item>
          <el-form-item label="补交月份">
            <div class="report-backfill">
              <div class="report-backfill-row">
                <el-select v-model="reportTargets.monthly" :loading="reportPeriodLoading.monthly" filterable placeholder="选择未提交月报月份">
                  <el-option v-for="item in reportPeriodOptions.monthly" :key="item.value" :label="item.label" :value="item.value" />
                </el-select>
                <el-button :loading="reportPeriodLoading.monthly" :disabled="!isEdit || !isReportEnabled('monthly') || !!reportMakeupAllLoading" @click="loadReportPeriodOptions('monthly')">刷新待补</el-button>
                <el-button type="danger" :loading="reportMakeupAllLoading === 'monthly'" :disabled="!isEdit || !isReportEnabled('monthly') || !!reportRunLoading || !!reportActionLoading || (!!reportMakeupAllLoading && reportMakeupAllLoading !== 'monthly') || !reportPendingCount('monthly')" @click="makeupAllReports('monthly')">补全部月报</el-button>
              </div>
              <el-progress
                v-if="reportMakeupAllInProgress('monthly')"
                class="report-backfill-progress"
                :percentage="reportMakeupAllPercent"
                :status="reportMakeupAllPercent >= 100 ? 'success' : undefined"
              />
              <div class="report-backfill-hint">{{ isReportEnabled('monthly') ? `月报待补 ${reportPendingCount('monthly')} 个周期` : '月报未开启，不获取待补周期' }}</div>
            </div>
          </el-form-item>
          <el-form-item label="月报预览">
            <div class="report-preview">
              <div class="report-preview-meta">
                <div>字数：{{ monthlyCount }} / {{ form.reportSettings.monthly.minWords }}–{{ form.reportSettings.monthly.maxWords }}</div>
                <div class="report-preview-actions">
                  <el-button size="small" :disabled="!isEdit || !isReportEnabled('monthly') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.monthly" :loading="reportActionLoading === 'monthly_generate'" @click="generateReport('monthly')">
                    AI生成月报
                  </el-button>
                  <el-button
                    size="small"
                    type="primary"
                    :disabled="!isEdit || !isReportEnabled('monthly') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.monthly || !String(reportPreview.monthly || '').trim()"
                    :loading="reportActionLoading === 'monthly_submit'"
                    @click="submitReport('monthly')"
                  >
                    提交月报
                  </el-button>
                  <el-button
                    size="small"
                    type="success"
                    :disabled="!isEdit || !isReportEnabled('monthly') || !!reportRunLoading || !!reportMakeupAllLoading || !reportTargets.monthly"
                    :loading="reportRunLoading === 'monthly_report'"
                    @click="runReportNow('monthly_report')"
                  >
                    立即执行月报
                  </el-button>
                </div>
              </div>
              <el-input v-model="reportPreview.monthly" type="textarea" :rows="6" resize="none" placeholder="点击 AI生成月报 或手动填写后提交" />
            </div>
          </el-form-item>
        </el-tab-pane>
        <el-tab-pane label="推送设置" name="push">
          <el-alert title="仅保留 Server酱 和 QQ 邮箱 SMTP 推送；QQ 邮箱 SMTP 的发件账号由管理员统一配置，这里只设置开关和收件邮箱。" type="info" :closable="false" style="margin-bottom: 15px;" />

          <el-divider content-position="left">Server酱</el-divider>
          <el-form-item label="启用 Server酱">
            <el-switch v-model="form.pushNotifications[0].enabled" />
          </el-form-item>
          <el-form-item label="SendKey">
            <el-input v-model="form.pushNotifications[0].sendKey" :placeholder="pushSecretPlaceholder" clearable />
          </el-form-item>

          <el-divider content-position="left">QQ 邮箱 SMTP</el-divider>
          <el-form-item label="启用 SMTP">
            <el-switch v-model="form.pushNotifications[1].enabled" />
          </el-form-item>
          <el-form-item label="收件邮箱">
            <el-input v-model="form.pushNotifications[1].to" placeholder="例如：demo@qq.com" />
          </el-form-item>
        </el-tab-pane>
      </el-tabs>

      <el-form-item v-if="!isMobile" class="desktop-actions">
        <div class="form-actions">
          <el-button type="primary" :loading="schedulePreviewLoading" @click="save">保存</el-button>
          <el-button @click="cancelEdit">取消</el-button>
        </div>
      </el-form-item>

      <div v-if="isMobile" class="mobile-actions-spacer"></div>
    </el-form>
  </el-card>

  <div v-if="isMobile" class="mobile-bottom-actions">
    <div class="mobile-bottom-actions-inner">
      <el-button type="primary" style="flex: 1" :loading="schedulePreviewLoading" @click="save">保存</el-button>
      <el-button style="flex: 1" @click="cancelEdit">取消</el-button>
    </div>
  </div>

  <el-dialog v-model="schedulePreviewVisible" title="未来打卡日期预览" width="min(680px, 94vw)" :close-on-click-modal="false">
    <el-alert :title="`时区：${schedulePreview.timezone || 'Asia/Shanghai'}；共 ${schedulePreview.dates.length} 个执行日期`" type="info" :closable="false" />
    <p class="preview-rule-note">每周打卡日与节假日排除规则共同过滤；启用跳过节假日时使用中国日历，日历不可用则按周末判断。</p>
    <p v-if="!schedulePreview.dates.length" class="preview-empty">当前规则没有未来执行日期。仍可确认保存，但请检查日期范围、每周打卡日及节假日设置。</p>
    <div v-else class="schedule-preview-dates">{{ schedulePreview.dates.join('、') }}</div>
    <template #footer>
      <el-button @click="schedulePreviewVisible = false">返回修改</el-button>
      <el-button type="primary" :loading="saving" @click="confirmScheduleAndSave">确认并保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http } from '../api/http'
import { ElMessageBox } from 'element-plus'
import ClockInPhotos from '../components/ClockInPhotos.vue'
import { countReportWords, validateClockInSchedule, validateReportContent, validateReportWordLimits, resolveSkipHolidays, hasLocationCoordinates, validLocationCoordinates } from '../utils/userRules'
import { canApplyPrefillLocation, credentialsMatch, hasAddressAndCoordinates, hasLocationValues, normalizeAccountInfo } from '../utils/accountPrefill'
import { useAuthStore } from '../stores/auth'
import { parseCnDotAddress, formatCnDotAddress, formatNearbyAddressPlace } from '../utils/cnAddress'
import { notifySuccess, notifyError, notifyWarning, notifyInfo, resolveErrorMessage } from '../utils/notify'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isEdit = computed(() => !!route.params.id)
const canRun = computed(() => auth.can('tasks:run'))
const passwordPlaceholder = computed(() => '请输入工学云密码')
const pushSecretPlaceholder = computed(() => '请输入')
const loading = ref(false)
const activeTab = ref('basic')
const DEFAULT_MAP_DISPLAY_URL = 'https://www.mapchaxun.cn/jingweidu'
const mapDisplayUrl = String(import.meta.env.VITE_MAP_DISPLAY_URL || DEFAULT_MAP_DISPLAY_URL).trim() || DEFAULT_MAP_DISPLAY_URL
const isMobile = ref(false)
const addrFillLoading = ref(false)
const accountRefreshLoading = ref(false)
const accountInfoLoading = ref(false)
const accountInfoProfile = ref(null)
const accountInfoReady = ref(false)
const accountInfoWarnings = ref([])
const accountInfoState = ref('idle')
const accountInfoFetched = ref(false)
const accountInfoAutoApplied = ref(false)
const accountInfoSummary = ref('')
let accountInfoNonce = 0
const accountLocation = ref(null)
const accountLocationMessage = ref('')
const schedulePreviewVisible = ref(false)
const schedulePreviewLoading = ref(false)
const saving = ref(false)
const schedulePreview = reactive({ dates: [], timezone: 'Asia/Shanghai' })
const clockInPeriodLoading = ref(false)
const clockInMakeupLoading = ref(false)
const clockInMakeupAllLoading = ref(false)
const clockInMakeupAllPercent = ref(0)
const clockInMakeupType = ref('START')
const clockInPeriodOptions = ref([])
const clockInTargetDates = ref([])
const clockInRecordCount = ref(0)
const reportRunLoading = ref('')
const reportActionLoading = ref('')
const reportPreview = reactive({ daily: '', weekly: '', monthly: '' })
const reportPeriodLoading = reactive({ daily: false, weekly: false, monthly: false })
const reportPeriodOptions = reactive({ daily: [], weekly: [], monthly: [] })
const reportMakeupAllLoading = ref('')
const reportMakeupAllPercent = ref(0)
const reportMakeupAllProgressKey = ref('')
const CLOCKIN_MAKEUP_REQUEST_TIMEOUT = 0
const REPORT_MAKEUP_REQUEST_TIMEOUT = 0
const _today = new Date()
const _pad2 = (n) => String(n).padStart(2, '0')
const _todayDate = `${_today.getFullYear()}-${_pad2(_today.getMonth() + 1)}-${_pad2(_today.getDate())}`
const _todayMonth = `${_today.getFullYear()}-${_pad2(_today.getMonth() + 1)}`
const reportTargets = reactive({ daily: _todayDate, weekly: _todayDate, monthly: _todayMonth })
let geocodeSearchAbort = null
let geocodeReverseAbort = null
let clockInMakeupAllTimer = null
let reportMakeupAllTimer = null

const resetClockInMakeupAllProgress = () => {
  if (clockInMakeupAllTimer) {
    clearInterval(clockInMakeupAllTimer)
    clockInMakeupAllTimer = null
  }
  clockInMakeupAllPercent.value = 0
}

const startClockInMakeupAllProgress = (total) => {
  resetClockInMakeupAllProgress()
  const count = Math.max(Number(total || 0), 1)
  const estimatedMs = Math.max(count * 2200, 3000)
  const startedAt = Date.now()
  clockInMakeupAllPercent.value = 3
  clockInMakeupAllTimer = setInterval(() => {
    const elapsed = Date.now() - startedAt
    clockInMakeupAllPercent.value = Math.min(95, Math.max(3, Math.round((elapsed / estimatedMs) * 95)))
  }, 300)
}

const finishClockInMakeupAllProgress = () => {
  if (clockInMakeupAllTimer) {
    clearInterval(clockInMakeupAllTimer)
    clockInMakeupAllTimer = null
  }
  clockInMakeupAllPercent.value = 100
  window.setTimeout(() => {
    if (!clockInMakeupAllLoading.value) clockInMakeupAllPercent.value = 0
  }, 1200)
}

const resetReportMakeupAllProgress = () => {
  if (reportMakeupAllTimer) {
    clearInterval(reportMakeupAllTimer)
    reportMakeupAllTimer = null
  }
  reportMakeupAllPercent.value = 0
  reportMakeupAllProgressKey.value = ''
}

const startReportMakeupAllProgress = (key, total) => {
  resetReportMakeupAllProgress()
  const count = Math.max(Number(total || 0), 1)
  const estimatedMs = Math.max(count * 4500, 5000)
  const startedAt = Date.now()
  reportMakeupAllProgressKey.value = key
  reportMakeupAllPercent.value = 3
  reportMakeupAllTimer = setInterval(() => {
    const elapsed = Date.now() - startedAt
    reportMakeupAllPercent.value = Math.min(95, Math.max(3, Math.round((elapsed / estimatedMs) * 95)))
  }, 300)
}

const finishReportMakeupAllProgress = () => {
  if (reportMakeupAllTimer) {
    clearInterval(reportMakeupAllTimer)
    reportMakeupAllTimer = null
  }
  reportMakeupAllPercent.value = 100
  window.setTimeout(() => {
    if (!reportMakeupAllLoading.value) resetReportMakeupAllProgress()
  }, 1200)
}

const flushUiMessage = async () => {
  await nextTick()
  await new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

const dailyCount = computed(() => countReportWords(reportPreview.daily))
const weeklyCount = computed(() => countReportWords(reportPreview.weekly))
const monthlyCount = computed(() => countReportWords(reportPreview.monthly))
const weekdayOptions = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 7 },
]

const buildDefaultPushNotifications = () => ([
  { type: 'Server', enabled: false, sendKey: '' },
  { type: 'SMTP', enabled: false, to: '' },
])

const normalizePushNotifications = (items) => {
  const list = Array.isArray(items) ? items : []
  const map = new Map(
    list
      .filter((item) => item && typeof item === 'object' && item.type)
      .map((item) => [item.type, { ...item }])
  )
  const server = map.get('Server') || {}
  const smtp = map.get('SMTP') || {}
  return [
    {
      type: 'Server',
      enabled: !!server.enabled,
      sendKey: typeof server.sendKey === 'string' ? server.sendKey : '',
    },
    {
      type: 'SMTP',
      enabled: !!smtp.enabled,
      to: typeof smtp.to === 'string' ? smtp.to : '',
    },
  ]
}

const form = reactive({
  phone: '',
  password: '',
  remark: '',
  enable_clockin: true,
  clockIn: {
    mode: 'custom',
    location: {
      address: '', latitude: '', longitude: '', province: '', city: '', area: ''
    },
    imageCount: 0,
    description: [],
    specialClockIn: false,
    customDays: [],
    schedule: {
      startTime: '08:30',
      endTime: '18:30',
      weekdays: [1, 2, 3, 4, 5, 6, 7],
      totalDays: 180,
      startDate: '',
      endDate: '',
      skipHolidays: false
    }
  },
  reportSettings: {
    daily: { enabled: false, imageCount: 0, submitTime: '12:00', submitDays: [1, 2, 3, 4, 5, 6, 7], minWords: 1, maxWords: 1000 },
    weekly: { enabled: false, imageCount: 0, submitTime: 5, submitAt: '18:30', minWords: 1, maxWords: 1000 },
    monthly: { enabled: false, imageCount: 0, submitTime: 29, submitAt: '12:00', minWords: 1, maxWords: 1000 }
  },
  pushNotifications: buildDefaultPushNotifications(),
  device: "{brand: TA J20, systemVersion: 17, Platform: Android, isPhysicalDevice: true, incremental: K23V10A}"
})

const searchQuery = computed({
  get: () => form.clockIn?.location?.address || '',
  set: (v) => {
    form.clockIn.location.address = String(v ?? '')
  },
})

const _cleanSegment = (v) => String(v || '').replace(/\s+/g, ' ').trim()

const _dedupeSegments = (segments) => {
  const out = []
  for (const s of segments) {
    const seg = _cleanSegment(s)
    if (!seg) continue
    if (out.length && out[out.length - 1] === seg) continue
    out.push(seg)
  }
  return out
}

const _composeAddress = (segments) => _dedupeSegments(segments).join(' · ')

const _pickFirst = (...vals) => {
  for (const v of vals) {
    const s = _cleanSegment(v)
    if (s) return s
  }
  return ''
}

const applyAddressStruct = (rawAddress, opts = {}) => {
  const input = String(rawAddress ?? '')
  const hasDot = /[·•]/.test(input)
  if (!hasDot && !opts?.force) return
  const parsed = parseCnDotAddress(input)
  if (parsed?.province) form.clockIn.location.province = parsed.province
  if (parsed?.province === '北京' || parsed?.province === '天津' || parsed?.province === '上海' || parsed?.province === '重庆') {
    form.clockIn.location.city = ''
  } else if (parsed?.city) {
    form.clockIn.location.city = parsed.city
  }
  if (parsed?.district) form.clockIn.location.area = parsed.district

  const rewriteAddress = typeof opts?.rewriteAddress === 'boolean' ? opts.rewriteAddress : hasDot
  if (rewriteAddress) {
    const normalized = formatCnDotAddress(parsed)
    if (normalized) form.clockIn.location.address = normalized
  }
}

const applyGeocodeAddress = (address, displayName = '', label = '') => {
    const addr = address && typeof address === 'object' ? address : {}
    const province = _pickFirst(addr.province, addr.state, addr.region, addr.state_district)
    const city = _pickFirst(addr.city, addr.town, addr.municipality, addr.county, addr.state_district)
    const area = _pickFirst(addr.city_district, addr.district, addr.county, addr.suburb, addr.borough, addr.village)

    if (province) form.clockIn.location.province = province
    if (city) form.clockIn.location.city = city
    if (area) form.clockIn.location.area = area

    const place = _pickFirst(label, addr.street_number, addr.street, displayName)
    form.clockIn.location.address = _composeAddress([province, city, area, formatNearbyAddressPlace(place || displayName)])
    applyAddressStruct(form.clockIn.location.address, { rewriteAddress: true })
}

const updateLocation = async (lat, lng, label = '', opts = {}) => {
    lat = Number.parseFloat(lat)
    lng = Number.parseFloat(lng)
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        notifyWarning('搜索结果经纬度无效，请换一个关键词')
        return false
    }
    
    form.clockIn.location.latitude = lat.toFixed(6);
    form.clockIn.location.longitude = lng.toFixed(6);
    
    if (label) {
        form.clockIn.location.address = _composeAddress(String(label).split(/[·,，]/g));
        applyAddressStruct(form.clockIn.location.address, { rewriteAddress: true })
    }

    if (opts?.address) {
        applyGeocodeAddress(opts.address, opts.displayName || '', label)
        if (opts.skipReverse) return true
    } else if (opts?.skipReverse) {
        return true
    }
    
    try {
        if (geocodeReverseAbort) geocodeReverseAbort.abort()
        geocodeReverseAbort = new AbortController()
        const res = await http.get('/geocode/reverse', { params: { lat, lon: lng }, signal: geocodeReverseAbort.signal })
        const payload = res.data?.result
        if (payload && payload.address) {
            const addr = payload.address;
            const province = _pickFirst(addr.province, addr.state, addr.region, addr.state_district)
            const city = _pickFirst(addr.city, addr.town, addr.municipality, addr.county, addr.state_district)
            const area = _pickFirst(addr.city_district, addr.district, addr.county, addr.suburb, addr.borough, addr.village)

            form.clockIn.location.province = province
            form.clockIn.location.city = city
            form.clockIn.location.area = area
            
            const fullAddr = _cleanSegment(payload.display_name)
            const place = _pickFirst(payload.name, fullAddr.split(',')[0])
            form.clockIn.location.address = _composeAddress([province, city, area, place])
            applyAddressStruct(form.clockIn.location.address, { rewriteAddress: true })
        }
    } catch (err) {
        if (err?.code === 'ERR_CANCELED') return
        console.error("逆地理编码失败", err);
        if (!label) {
             notifyWarning(err.response?.data?.detail || '无法自动获取详细地址，请手动填写')
        }
    }
    return true
}

const normalizeSearchQuery = (q) => {
  return String(q || '')
    .replace(/·/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

const goBack = () => {
  notifyInfo('正在返回上一页')
  router.back()
}

const goPreauthorization = () => {
  if (!isEdit.value || !canRun.value) return
  router.push(`/users/${route.params.id}/preauthorizations`)
}

const searchPlace = async () => {
    const q = normalizeSearchQuery(searchQuery.value)
    if (!q) {
        notifyWarning('请输入要搜索的地点')
        return
    }
    try {
        if (geocodeSearchAbort) geocodeSearchAbort.abort()
        geocodeSearchAbort = new AbortController()
        const res = await http.get('/geocode/search', { params: { q }, signal: geocodeSearchAbort.signal })
        const results = res.data?.results || []
        if (!Array.isArray(results) || results.length === 0) {
            notifyWarning('没有搜索到结果，请换一个关键词')
            return
        }
        const best = results[0]
        const lat = Number(best.y)
        const lng = Number(best.x)
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
            notifyWarning('搜索结果经纬度无效，请换一个关键词')
            return
        }
        const address = best.address || best.raw?.address_components || best.raw?.result?.address_components

        const updated = await updateLocation(lat, lng, best.label || q, {
            address,
            displayName: best.raw?.adress || best.raw?.result?.title || best.label || q,
            skipReverse: !!address,
        })
        if (!updated) return
        notifySuccess('已定位到搜索结果')
    } catch (e) {
        if (e?.code === 'ERR_CANCELED') return
        notifyError(e.response?.data?.detail || '搜索失败，请稍后再试')
    }
}

const setAccountLocation = (candidate, message = '') => {
  accountLocation.value = candidate && typeof candidate === 'object' ? {
    address: String(candidate.address || ''),
    latitude: candidate.latitude ?? '',
    longitude: candidate.longitude ?? '',
    province: String(candidate.province || ''),
    city: String(candidate.city || ''),
    area: String(candidate.area || ''),
    source: String(candidate.source || ''),
  } : null
  accountLocationMessage.value = String(message || (accountLocation.value ? '' : '没有可用的账号位置候选'))
}

const fetchNewAccountInfo = async () => {
  if (isEdit.value || accountInfoLoading.value || !form.phone.trim() || !form.password.trim()) return
  const captured = { phone: form.phone, password: form.password }
  const phone = form.phone.trim()
  const requestNonce = ++accountInfoNonce
  const isCurrentRequest = () => requestNonce === accountInfoNonce && credentialsMatch(captured, form)
  accountInfoLoading.value = true
  if (accountInfoState.value !== 'expired') accountInfoState.value = 'loading'
  try {
    const res = await http.post('/users/account-info', { phone, password: captured.password }, { timeout: 120000 })
    if (!isCurrentRequest()) return
    const result = normalizeAccountInfo(res.data)
    if (!result.ok) {
      accountInfoState.value = accountInfoState.value === 'expired' ? 'expired' : (accountInfoFetched.value ? 'ready' : 'idle')
      notifyWarning(result.locationMessage || '未能获取账号信息，请核对凭据后重试')
      return
    }

    accountInfoProfile.value = result.profile
    accountInfoReady.value = result.ready
    accountInfoWarnings.value = [...result.warnings]
    accountInfoFetched.value = true
    accountInfoState.value = 'ready'
    const profile = result.profile
    const summaryItems = [
      profile.name && `姓名：${profile.name}`,
      profile.schoolName && `学校：${profile.schoolName}`,
      profile.companyName && `企业：${profile.companyName}`,
      profile.companyAddress && `企业地址：${profile.companyAddress}`,
      profile.jobAddress && `打卡地址：${profile.jobAddress}`,
      profile.planName && `计划：${profile.planName}`,
      `位置来源：${result.accountLocation?.source || '未读取到'}`,
      `位置状态：${result.ready ? '完整' : '未完整'}`,
    ].filter(Boolean)
    accountInfoSummary.value = [...summaryItems, result.locationMessage].filter(Boolean).join('；')
    setAccountLocation(result.accountLocation, result.locationMessage)

    if (!canApplyPrefillLocation(result.accountLocation)) {
      const warning = '没有读取到有效经纬度，未自动填写打卡位置；可在打卡设置中手动核对填写'
      if (!accountInfoWarnings.value.includes(warning)) accountInfoWarnings.value.push(warning)
      notifyWarning(result.locationMessage || warning)
      return
    }

    const hadExistingLocation = hasLocationValues(form.clockIn.location) || accountInfoAutoApplied.value
    if (hadExistingLocation) {
      try {
        await ElMessageBox.confirm(
          '打卡设置中已有位置。获取账号位置将覆盖现有地址、坐标和省市区，是否继续？',
          '确认替换打卡位置',
          { type: 'warning', confirmButtonText: '覆盖并应用', cancelButtonText: '保留现有位置' }
        )
      } catch {
        return
      }
      if (!isCurrentRequest()) return
    }
    const location = result.accountLocation
    form.clockIn.location.address = location.address
    form.clockIn.location.latitude = location.latitude
    form.clockIn.location.longitude = location.longitude
    form.clockIn.location.province = location.province
    form.clockIn.location.city = location.city
    form.clockIn.location.area = location.area
    accountInfoAutoApplied.value = true
    notifySuccess(result.ready ? '账号信息已获取，位置已自动填写；核对摘要后即可保存' : '账号简介已获取，现有坐标已填写；位置尚未完整，请核对后保存')
  } catch (error) {
    if (!isCurrentRequest()) return
    accountInfoState.value = accountInfoState.value === 'expired' ? 'expired' : (accountInfoFetched.value ? 'ready' : 'idle')
    notifyError(resolveErrorMessage(error, '获取账号信息失败'))
  } finally {
    if (requestNonce === accountInfoNonce) accountInfoLoading.value = false
  }
}

const canApplyAccountLocation = computed(() => validLocationCoordinates(accountLocation.value))

const applyAccountLocation = async () => {
  if (!canApplyAccountLocation.value || !accountLocation.value) {
    notifyWarning('候选位置缺少有效经纬度，不能应用')
    return
  }
  const hasExistingCoordinates = hasLocationCoordinates(form.clockIn.location)
  if (hasExistingCoordinates) {
    try {
      await ElMessageBox.confirm('打卡设置中已有经纬度。应用候选位置会覆盖现有地址和坐标，是否继续？', '确认覆盖打卡位置', { type: 'warning', confirmButtonText: '覆盖并应用', cancelButtonText: '取消' })
    } catch {
      return
    }
  }
  const location = accountLocation.value
  form.clockIn.location.address = location.address
  form.clockIn.location.latitude = Number(location.latitude).toFixed(6)
  form.clockIn.location.longitude = Number(location.longitude).toFixed(6)
  form.clockIn.location.province = location.province
  form.clockIn.location.city = location.city
  form.clockIn.location.area = location.area
  notifySuccess('候选位置已应用到打卡设置；保存用户后才会持久化')
}

const fetchUser = async () => {
  if (!isEdit.value) return
  loading.value = true
  try {
    const res = await http.get(`/users/${route.params.id}`)
    const userData = { ...(res.data || {}) }
    setAccountLocation(userData.accountLocation, userData.locationMessage)
    delete userData.accountLocation
    delete userData.locationMessage
    Object.assign(form, userData)
    delete form.ai
    const last = res.data?.last_execution_result || []
    if (Array.isArray(last)) {
      reportPreview.daily = (last.find(i => i?.task_type === '日报提交' && i?.report_content)?.report_content) || ''
      reportPreview.weekly = (last.find(i => i?.task_type === '周报提交' && i?.report_content)?.report_content) || ''
      reportPreview.monthly = (last.find(i => i?.task_type === '月报提交' && i?.report_content)?.report_content) || ''
    }
    if (!form.clockIn) {
      form.clockIn = {}
    }
    if (!form.clockIn.location) form.clockIn.location = { address: '', latitude: '', longitude: '', province: '', city: '', area: '' }
    if (!form.clockIn.schedule) {
      form.clockIn.schedule = { startTime: '08:30', endTime: '18:30', weekdays: [1,2,3,4,5,6,7], totalDays: 180, startDate: '', endDate: '', skipHolidays: resolveSkipHolidays(form.clockIn.mode) }
    } else {
      if (!form.clockIn.schedule.startTime) form.clockIn.schedule.startTime = '08:30'
      if (!form.clockIn.schedule.endTime) form.clockIn.schedule.endTime = '18:30'
      if (!Array.isArray(form.clockIn.schedule.weekdays)) {
        form.clockIn.schedule.weekdays = Array.isArray(form.clockIn.customDays) && form.clockIn.customDays.length ? form.clockIn.customDays : [1,2,3,4,5,6,7]
      }
      if (!form.clockIn.schedule.totalDays) form.clockIn.schedule.totalDays = 180
      if (!form.clockIn.schedule.startDate) form.clockIn.schedule.startDate = ''
      if (typeof form.clockIn.schedule.endDate !== 'string') form.clockIn.schedule.endDate = ''
      form.clockIn.schedule.skipHolidays = resolveSkipHolidays(form.clockIn.mode, form.clockIn.schedule.skipHolidays, form.clockIn.specialClockIn)
    }
    if (!form.reportSettings) {
      form.reportSettings = { daily: {}, weekly: {}, monthly: {} }
    }
    if (!form.reportSettings.daily) {
      form.reportSettings.daily = { enabled: false, imageCount: 0, submitTime: '12:00', submitDays: [1, 2, 3, 4, 5, 6, 7], minWords: 1, maxWords: 1000 }
    } else {
      if (!form.reportSettings.daily.submitTime) form.reportSettings.daily.submitTime = '12:00'
      if (!Array.isArray(form.reportSettings.daily.submitDays)) {
        form.reportSettings.daily.submitDays = [1, 2, 3, 4, 5, 6, 7]
      }
      if (form.reportSettings.daily.minWords == null) form.reportSettings.daily.minWords = 1
      if (form.reportSettings.daily.maxWords == null) form.reportSettings.daily.maxWords = 1000
    }
    if (!form.reportSettings.weekly) {
      form.reportSettings.weekly = { enabled: false, imageCount: 0, submitTime: 5, submitAt: '18:30', minWords: 1, maxWords: 1000 }
    } else {
      if (typeof form.reportSettings.weekly.enabled !== 'boolean') form.reportSettings.weekly.enabled = false
      if (form.reportSettings.weekly.minWords == null) form.reportSettings.weekly.minWords = 1
      if (form.reportSettings.weekly.maxWords == null) form.reportSettings.weekly.maxWords = 1000
      if (!form.reportSettings.weekly.submitTime) form.reportSettings.weekly.submitTime = 5
      if (!form.reportSettings.weekly.submitAt) form.reportSettings.weekly.submitAt = '18:30'
    }
    if (!form.reportSettings.monthly) {
      form.reportSettings.monthly = { enabled: false, imageCount: 0, submitTime: 29, submitAt: '12:00', minWords: 1, maxWords: 1000 }
    } else {
      if (form.reportSettings.monthly.minWords == null) form.reportSettings.monthly.minWords = 1
      if (form.reportSettings.monthly.maxWords == null) form.reportSettings.monthly.maxWords = 1000
      if (form.reportSettings.monthly.submitTime == null || form.reportSettings.monthly.submitTime === '') form.reportSettings.monthly.submitTime = 29
      if (!form.reportSettings.monthly.submitAt) form.reportSettings.monthly.submitAt = '12:00'
    }
    form.pushNotifications = normalizePushNotifications(form.pushNotifications)
  } catch (error) {
    notifyError('加载失败')
  } finally {
    loading.value = false
  }
}

const _clone = (obj) => JSON.parse(JSON.stringify(obj))

const defaultFormSnapshot = _clone(form)

const resetToDefaultForm = () => {
  const next = _clone(defaultFormSnapshot)
  for (const k of Object.keys(form)) {
    if (!(k in next)) delete form[k]
  }
  for (const [k, v] of Object.entries(next)) {
    form[k] = v
  }
  reportPreview.daily = ''
  reportPreview.weekly = ''
  reportPreview.monthly = ''
  activeTab.value = 'basic'
}

const validateFormBeforePreview = () => {
  const scheduleMessage = validateClockInSchedule(form.clockIn)
  if (scheduleMessage) return scheduleMessage
  for (const key of reportKeys) {
    const settings = form.reportSettings?.[key] || {}
    const limits = validateReportWordLimits(settings.minWords ?? 1, settings.maxWords ?? 1000)
    if (!limits.valid) return `${reportLabelMap[key]}：${limits.message}`
  }
  return ''
}

const accountPrefillSaveBlocker = () => {
  if (isEdit.value) return ''
  if (accountInfoState.value === 'expired') return '新增用户账号或密码已变更，请重新获取账号信息后再保存'
  if (accountInfoLoading.value) return '请等待账号信息获取完成后再保存'
  if (accountInfoFetched.value && form.enable_clockin && !hasAddressAndCoordinates(form.clockIn.location)) {
    return '账号信息位置未完整：请补全有效地址和经纬度，或明确关闭自动打卡后再保存'
  }
  return ''
}

const persistUserAfterPreview = async () => {
  const blocker = accountPrefillSaveBlocker()
  if (blocker) throw new Error(blocker)
  form.clockIn.mode = 'custom'
  form.clockIn.customDays = form.clockIn.schedule.weekdays
  const payload = JSON.parse(JSON.stringify(form))
  delete payload.ai
  delete payload.accountLocation
  delete payload.locationMessage
  payload.pushNotifications = normalizePushNotifications(payload.pushNotifications)
  if (isEdit.value) {
    await http.patch(`/users/${route.params.id}`, payload)
  } else {
    await http.post('/users', payload)
  }
  schedulePreviewVisible.value = false
  notifySuccess('保存成功')
  if (isEdit.value) {
    await fetchUser()
  } else {
    await router.push('/')
  }
}

const save = async () => {
  if (schedulePreviewLoading.value || saving.value) return
  const prefillBlocker = accountPrefillSaveBlocker()
  if (prefillBlocker) {
    notifyWarning(prefillBlocker)
    return
  }
  const validationMessage = validateFormBeforePreview()
  if (validationMessage) {
    notifyWarning(validationMessage)
    return
  }
  schedulePreviewLoading.value = true
  try {
    notifyInfo('保存前先预览未来打卡日期')
    await flushUiMessage()
    const clockIn = JSON.parse(JSON.stringify(form.clockIn))
    const res = await http.post('/schedule/preview', { clockIn })
    const blockerAfterPreview = accountPrefillSaveBlocker()
    if (blockerAfterPreview) {
      notifyWarning(blockerAfterPreview)
      return
    }
    if (!Array.isArray(res.data?.dates)) throw new Error('预览接口未返回 dates 日期列表')
    schedulePreview.dates = res.data.dates.filter((date) => typeof date === 'string')
    schedulePreview.timezone = String(res.data.timezone || 'Asia/Shanghai')
    schedulePreviewVisible.value = true
  } catch (error) {
    notifyError(`日期预览失败，未保存：${resolveErrorMessage(error, '请稍后重试')}`)
  } finally {
    schedulePreviewLoading.value = false
  }
}

const confirmScheduleAndSave = async () => {
  if (saving.value) return
  const blocker = accountPrefillSaveBlocker()
  if (blocker) {
    notifyWarning(blocker)
    return
  }
  saving.value = true
  try {
    await persistUserAfterPreview()
  } catch (error) {
    notifyError(`保存失败：${resolveErrorMessage(error, '请求失败')}`)
  } finally {
    saving.value = false
  }
}

const cancelEdit = () => {
  if (isEdit.value) {
    fetchUser()
    notifyInfo('已撤销未保存的修改')
    return
  }
  resetToDefaultForm()
  notifyInfo('已清空未保存的内容')
}

const reportLabelMap = { daily: '日报', weekly: '周报', monthly: '月报' }
const reportTaskMap = { daily: 'daily_report', weekly: 'weekly_report', monthly: 'monthly_report' }
const reportKeys = ['daily', 'weekly', 'monthly']
const isReportEnabled = (key) => !!form.reportSettings?.[key]?.enabled
const clockInMakeupTypeLabel = computed(() => (clockInMakeupType.value === 'END' ? '下班' : '上班'))
const reportPendingCount = (key) => (Array.isArray(reportPeriodOptions[key]) ? reportPeriodOptions[key].length : 0)
const reportMakeupAllInProgress = (key) => reportMakeupAllProgressKey.value === key && (reportMakeupAllLoading.value === key || reportMakeupAllPercent.value > 0)
const clearReportPeriodOptions = (key) => {
  reportPeriodOptions[key] = []
  reportTargets[key] = ''
}
const filteredClockInPeriodOptions = computed(() => {
  const options = Array.isArray(clockInPeriodOptions.value) ? clockInPeriodOptions.value : []
  return options
    .filter((item) => Array.isArray(item.missing_types) && item.missing_types.includes(clockInMakeupType.value))
    .map((item) => ({ ...item, label: `${item.value}（缺${clockInMakeupTypeLabel.value}）` }))
})
const syncClockInTargetFromOptions = () => {
  const options = filteredClockInPeriodOptions.value
  if (!options.length) {
    clockInTargetDates.value = []
    return
  }
  const validValues = new Set(options.map((item) => item.value))
  const selected = Array.isArray(clockInTargetDates.value) ? clockInTargetDates.value : []
  clockInTargetDates.value = selected.filter((item) => validValues.has(item))
  if (!clockInTargetDates.value.length) {
    clockInTargetDates.value = [options[0].value]
  }
}

const loadClockInMissingDays = async () => {
  if (!isEdit.value) return
  clockInPeriodLoading.value = true
  try {
    const res = await http.get(`/users/${route.params.id}/clock-in/missing-days`)
    clockInPeriodOptions.value = Array.isArray(res.data?.options) ? res.data.options : []
    clockInRecordCount.value = Number(res.data?.record_count || 0)
    syncClockInTargetFromOptions()
  } catch (e) {
    clockInPeriodOptions.value = []
    clockInRecordCount.value = 0
    clockInTargetDates.value = []
    notifyWarning(resolveErrorMessage(e, '获取缺卡日期失败'))
  } finally {
    clockInPeriodLoading.value = false
  }
}

const makeupClockIn = async () => {
  if (!isEdit.value) return
  const targetDates = Array.isArray(clockInTargetDates.value) ? clockInTargetDates.value : []
  if (!targetDates.length) {
    notifyWarning('暂无可补卡日期')
    return
  }
  clockInMakeupLoading.value = true
  try {
    notifyInfo('正在补卡')
    await flushUiMessage()
    const res = await http.post(`/users/${route.params.id}/clock-in/makeup`, {
      target_dates: targetDates,
      target_type: clockInMakeupType.value,
    }, { timeout: CLOCKIN_MAKEUP_REQUEST_TIMEOUT })
    const result = res.data?.result || {}
    if (result.status === 'success') {
      notifySuccess(result.message || '补卡完成')
    } else if (result.status === 'skip') {
      notifyWarning(result.message || '已跳过补卡')
    } else {
      notifyError(result.message || '补卡失败')
    }
    await loadClockInMissingDays()
  } catch (e) {
    notifyError(resolveErrorMessage(e, '补卡失败'))
  } finally {
    clockInMakeupLoading.value = false
  }
}

const makeupAllClockIn = async () => {
  if (!isEdit.value) return
  if (!filteredClockInPeriodOptions.value.length) {
    notifyWarning('暂无待补卡日期')
    return
  }
  clockInMakeupAllLoading.value = true
  startClockInMakeupAllProgress(filteredClockInPeriodOptions.value.length)
  try {
    notifyInfo('正在补全部待补日期')
    await flushUiMessage()
    const res = await http.post(`/users/${route.params.id}/clock-in/makeup-all`, {
      target_type: clockInMakeupType.value,
    }, { timeout: CLOCKIN_MAKEUP_REQUEST_TIMEOUT })
    const result = res.data?.result || {}
    if (result.status === 'success') {
      notifySuccess(result.message || '全部补卡完成')
    } else if (result.status === 'skip') {
      notifyWarning(result.message || '已跳过补卡')
    } else {
      notifyError(result.message || '全部补卡失败')
    }
    finishClockInMakeupAllProgress()
    await loadClockInMissingDays()
  } catch (e) {
    resetClockInMakeupAllProgress()
    notifyError(resolveErrorMessage(e, '全部补卡失败'))
  } finally {
    clockInMakeupAllLoading.value = false
  }
}

const getReportTarget = (key) => String(reportTargets[key] || '').trim() || undefined
const hasReportTarget = (key) => !!getReportTarget(key)
const syncReportTargetFromOptions = (key) => {
  const options = Array.isArray(reportPeriodOptions[key]) ? reportPeriodOptions[key] : []
  if (!options.length) {
    reportTargets[key] = ''
    return
  }
  if (!options.some((item) => item.value === reportTargets[key])) {
    reportTargets[key] = options[0].value
  }
}

const loadReportPeriodOptions = async (key) => {
  if (!isEdit.value) return
  if (!isReportEnabled(key)) {
    clearReportPeriodOptions(key)
    notifyWarning(`${reportLabelMap[key] || '报告'}未开启，不获取待补周期`)
    return
  }
  reportPeriodLoading[key] = true
  try {
    const res = await http.get(`/users/${route.params.id}/reports/${key}/missing-periods`)
    reportPeriodOptions[key] = Array.isArray(res.data?.options) ? res.data.options : []
    syncReportTargetFromOptions(key)
  } catch (e) {
    reportPeriodOptions[key] = []
    reportTargets[key] = ''
    notifyWarning(resolveErrorMessage(e, `获取${reportLabelMap[key] || '报告'}未提交周期失败`))
  } finally {
    reportPeriodLoading[key] = false
  }
}

const loadAllReportPeriodOptions = async () => {
  if (!isEdit.value) return
  reportKeys.filter((key) => !isReportEnabled(key)).forEach(clearReportPeriodOptions)
  await Promise.all(reportKeys.filter(isReportEnabled).map((key) => loadReportPeriodOptions(key)))
}

const generateReport = async (key) => {
  if (!isEdit.value) return
  const label = reportLabelMap[key] || '报告'
  if (!isReportEnabled(key)) {
    notifyWarning(`${label}未开启`)
    return
  }
  if (!hasReportTarget(key)) {
    notifyWarning(`暂无可补交的${label}周期`)
    return
  }
  reportActionLoading.value = `${key}_generate`
  try {
    notifyInfo(`正在生成${label}`)
    await flushUiMessage()
    const res = await http.post(`/users/${route.params.id}/reports/${key}/generate`, null, {
      params: { target_period: getReportTarget(key) },
    })
    reportPreview[key] = String(res.data?.content || '')
    notifySuccess(`${label}已生成`)
  } catch (e) {
    notifyError(resolveErrorMessage(e, `${label}生成失败`))
  } finally {
    reportActionLoading.value = ''
  }
}

const submitReport = async (key) => {
  if (!isEdit.value) return
  const label = reportLabelMap[key] || '报告'
  if (!isReportEnabled(key)) {
    notifyWarning(`${label}未开启`)
    return
  }
  if (!hasReportTarget(key)) {
    notifyWarning(`暂无可补交的${label}周期`)
    return
  }
  const content = String(reportPreview[key] || '')
  const contentValidation = validateReportContent(content, form.reportSettings?.[key] || {})
  if (!contentValidation.valid) {
    notifyWarning(contentValidation.count === 0 ? `请先生成或填写${label}内容` : contentValidation.message)
    return
  }
  reportActionLoading.value = `${key}_submit`
  try {
    notifyInfo(`正在提交${label}`)
    await flushUiMessage()
    const res = await http.post(`/users/${route.params.id}/reports/${key}/submit`, {
      content,
      target_period: getReportTarget(key),
    })
    notifySuccess(`提交成功：${res.data?.title || label}`)
    await loadReportPeriodOptions(key)
  } catch (e) {
    notifyError(resolveErrorMessage(e, `${label}提交失败`))
  } finally {
    reportActionLoading.value = ''
  }
}

const makeupAllReports = async (key) => {
  if (!isEdit.value) return
  const label = reportLabelMap[key] || '报告'
  if (!isReportEnabled(key)) {
    clearReportPeriodOptions(key)
    notifyWarning(`${label}未开启`)
    return
  }
  const total = reportPendingCount(key)
  if (!total) {
    notifyWarning(`暂无待补交${label}周期`)
    return
  }
  reportMakeupAllLoading.value = key
  startReportMakeupAllProgress(key, total)
  try {
    notifyInfo(`正在补交全部待补${label}`)
    await flushUiMessage()
    const res = await http.post(`/users/${route.params.id}/reports/${key}/makeup-all`, null, {
      timeout: REPORT_MAKEUP_REQUEST_TIMEOUT,
    })
    const result = res.data?.result || {}
    if (result.status === 'success') {
      notifySuccess(result.message || `全部${label}补交完成`)
    } else if (result.status === 'skip') {
      notifyWarning(result.message || `已跳过${label}补交`)
    } else {
      notifyError(result.message || `全部${label}补交失败`)
    }
    finishReportMakeupAllProgress()
    await fetchUser()
    await loadReportPeriodOptions(key)
  } catch (e) {
    resetReportMakeupAllProgress()
    notifyError(resolveErrorMessage(e, `全部${label}补交失败`))
  } finally {
    reportMakeupAllLoading.value = ''
  }
}

const runReportNow = async (taskType) => {
  if (!isEdit.value) return
  const labelMap = {
    daily_report: '日报',
    weekly_report: '周报',
    monthly_report: '月报',
  }
  const label = labelMap[taskType] || '报告'
  const key = Object.keys(reportTaskMap).find((item) => reportTaskMap[item] === taskType)
  if (!isReportEnabled(key)) {
    notifyWarning(`${label}未开启`)
    return
  }
  if (!hasReportTarget(key)) {
    notifyWarning(`暂无可补交的${label}周期`)
    return
  }
  reportRunLoading.value = taskType
  try {
    notifyInfo(`正在立即执行${label}`)
    await flushUiMessage()
    const res = await http.post(`/users/${route.params.id}/run`, {
      task_type: taskType,
      force_report: true,
      target_period: getReportTarget(key),
    })
    const results = Array.isArray(res.data?.results) ? res.data.results : []
    const first = results[0] || {}
    if (first.report_content) {
      if (taskType === 'daily_report') reportPreview.daily = first.report_content
      if (taskType === 'weekly_report') reportPreview.weekly = first.report_content
      if (taskType === 'monthly_report') reportPreview.monthly = first.report_content
    }
    if (first.status === 'success') {
      notifySuccess(first.message || `${label}已提交`)
    } else if (first.status === 'skip') {
      notifyWarning(first.message || `${label}已跳过`)
    } else {
      notifyError(first.message || `${label}执行失败`)
    }
    await fetchUser()
    if (key) await loadReportPeriodOptions(key)
  } catch (e) {
    notifyError(resolveErrorMessage(e, `${label}执行失败`))
  } finally {
    reportRunLoading.value = ''
  }
}

const _pickBestAddress = (...values) => {
  const list = []
  for (const v of values.flat(2)) {
    const s = String(v || '').trim()
    if (s) list.push(s)
  }
  if (!list.length) return ''
  const unique = []
  for (const s of list) {
    if (!unique.includes(s)) unique.push(s)
  }
  unique.sort((x, y) => y.length - x.length)
  return unique[0] || ''
}

const refreshAccountLocation = async () => {
  if (!isEdit.value) return
  accountRefreshLoading.value = true
  try {
    notifyInfo('正在获取账号信息与上班位置候选（仅查询，不会修改用户）')
    await flushUiMessage()
    const res = await http.post(`/users/${route.params.id}/refresh`)
    setAccountLocation(res.data?.accountLocation, res.data?.locationMessage || (res.data?.ok ? '账号信息已获取；没有提取到可用位置候选' : '未能获取账号信息'))
    if (accountLocation.value) notifySuccess('账号位置候选已更新；请核对后手动应用')
    else notifyWarning(accountLocationMessage.value)
  } catch (e) {
    notifyError(resolveErrorMessage(e, '获取账号信息失败'))
  } finally {
    accountRefreshLoading.value = false
  }
}

const fillFromAccountAddress = async () => {
  if (!isEdit.value) return
  addrFillLoading.value = true
  try {
    notifyInfo('正在读取账号位置候选（不会自动应用）')
    await flushUiMessage()
    const res = await http.get(`/users/${route.params.id}/account-address`)
    setAccountLocation(res.data?.accountLocation, res.data?.locationMessage || (res.data?.accountLocation ? '' : '账号地址接口未返回可用位置候选'))
    if (accountLocation.value) notifySuccess('账号位置候选已更新；请核对后手动应用')
    else notifyWarning(accountLocationMessage.value)
  } catch (e) {
    notifyError(resolveErrorMessage(e, '读取账号地址候选失败'))
  } finally {
    addrFillLoading.value = false
  }
}

watch(
  () => [form.phone, form.password],
  () => {
    accountInfoNonce += 1
    accountInfoLoading.value = false
    if (accountInfoFetched.value) {
      accountInfoState.value = 'expired'
      accountInfoProfile.value = null
      accountInfoReady.value = false
      accountInfoWarnings.value = []
      accountInfoSummary.value = '账号或密码已改变；请重新获取账号信息。旧位置仍保留但不会允许保存。'
      setAccountLocation(null, '凭据已变更，之前读取的位置不再可信')
    } else if (accountInfoState.value === 'loading') {
      accountInfoState.value = 'idle'
    }
  },
  { flush: 'sync' }
)

watch(
  () => reportKeys.map((key) => isReportEnabled(key)).join('|'),
  () => {
    reportKeys.filter((key) => !isReportEnabled(key)).forEach(clearReportPeriodOptions)
  }
)

onMounted(async () => {
    await fetchUser();
})

let addrStructTimer = null
watch(
  () => form.clockIn?.location?.address,
  (val) => {
    const s = String(val || '').trim()
    if (!s) return
    if (!/[·•]/.test(s)) return
    if (addrStructTimer) clearTimeout(addrStructTimer)
    addrStructTimer = setTimeout(() => {
      applyAddressStruct(s)
    }, 350)
  }
)

const updateIsMobile = () => {
  isMobile.value = window.matchMedia('(max-width: 768px)').matches
}

onMounted(() => {
  updateIsMobile()
  let raf = 0
  const onResize = () => {
    if (raf) return
    raf = requestAnimationFrame(() => {
      raf = 0
      updateIsMobile()
    })
  }
  window.addEventListener('resize', onResize)
  onUnmounted(() => {
    if (raf) cancelAnimationFrame(raf)
    window.removeEventListener('resize', onResize)
  })
})
onUnmounted(() => {
  if (addrStructTimer) clearTimeout(addrStructTimer)
  resetClockInMakeupAllProgress()
  resetReportMakeupAllProgress()
  if (geocodeSearchAbort) geocodeSearchAbort.abort()
  if (geocodeReverseAbort) geocodeReverseAbort.abort()
})
</script>

<style scoped>
.desktop-actions {
  margin-top: 20px;
}
.account-location-alert {
  margin: 0 0 14px 0;
}
.account-location-candidate {
  margin: 0 0 20px;
  padding: 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
}
.word-range {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.schedule-preview-dates {
  margin-top: 14px;
  max-height: 45vh;
  overflow: auto;
  line-height: 1.9;
  overflow-wrap: anywhere;
}
.preview-rule-note {
  margin: 10px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.preview-empty {
  color: var(--el-color-warning);
  margin: 14px 0 0;
}
.map {
  height: 300px;
  margin-bottom: 20px;
  border-radius: 4px;
  border: 1px solid var(--el-border-color);
  overflow: hidden;
  z-index: 1;
}
.external-map iframe {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}
.place-row {
  display: flex;
  gap: 10px;
  width: 100%;
}
.place-input {
  flex: 1;
  min-width: 0;
}
.place-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.place-actions :deep(.el-button) {
  white-space: nowrap;
}
.calendar-days-setting {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.calendar-days-setting span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.week-group {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.clockin-backfill {
  width: 100%;
}
.clockin-backfill-row {
  width: 100%;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.clockin-backfill-row :deep(.el-select) {
  flex: 1 1 240px;
}
.clockin-backfill-row :deep(.clockin-type-select) {
  flex: 0 0 120px;
}
.clockin-backfill-progress {
  margin-top: 10px;
  max-width: 520px;
}
.clockin-backfill-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.report-backfill {
  width: 100%;
}
.report-backfill-row {
  width: 100%;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.report-backfill-row :deep(.el-select) {
  flex: 1 1 240px;
}
.report-backfill-progress {
  margin-top: 10px;
  max-width: 520px;
}
.report-backfill-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.form-actions {
  display: flex;
  gap: 12px;
}
.mobile-actions-spacer {
  height: calc(68px + env(safe-area-inset-bottom));
}
.mobile-bottom-actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  border-top: 1px solid var(--el-border-color);
  background-color: var(--el-bg-color);
  padding: 10px calc(12px + env(safe-area-inset-left)) calc(10px + env(safe-area-inset-bottom)) calc(12px + env(safe-area-inset-right));
  z-index: 1500;
}
.mobile-bottom-actions-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  gap: 12px;
}
.report-preview {
  width: 100%;
}
.report-preview-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.report-preview-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
@media (max-width: 768px) {
  .map {
    height: 240px;
    margin-bottom: 16px;
  }
  .place-actions {
    margin-top: 8px;
  }
  .place-row {
    flex-direction: column;
  }
  .place-actions {
    width: 100%;
    justify-content: stretch;
  }
  .place-actions :deep(.el-button) {
    flex: 1;
  }
}
</style>
