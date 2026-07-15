import { defineAsyncComponent, type Component } from 'vue'
import {
  ElCascader,
  ElCheckboxGroup,
  ElColorPicker,
  ElDatePicker,
  ElInput,
  ElInputNumber,
  ElRadioGroup,
  ElRate,
  ElSelect,
  ElSelectV2,
  ElSlider,
  ElSwitch,
  ElTimePicker,
  ElTimeSelect,
  ElTransfer,
  ElAutocomplete,
  ElDivider,
  ElTreeSelect,
  ElUpload
} from 'element-plus'
import { InputPassword } from '@/components/InputPassword'
import { IAgree } from '@/components/IAgree'
import { ComponentName } from '../types'

const componentMap: Recordable<Component, ComponentName> = {
  RadioGroup: ElRadioGroup,
  RadioButton: ElRadioGroup,
  CheckboxGroup: ElCheckboxGroup,
  CheckboxButton: ElCheckboxGroup,
  Input: ElInput,
  Autocomplete: ElAutocomplete,
  InputNumber: ElInputNumber,
  Select: ElSelect,
  Cascader: ElCascader,
  Switch: ElSwitch,
  Slider: ElSlider,
  TimePicker: ElTimePicker,
  DatePicker: ElDatePicker,
  Rate: ElRate,
  ColorPicker: ElColorPicker,
  Transfer: ElTransfer,
  Divider: ElDivider,
  TimeSelect: ElTimeSelect,
  SelectV2: ElSelectV2,
  InputPassword: InputPassword,
  Editor: defineAsyncComponent(() => import('@/components/Editor').then((module) => module.Editor)),
  TreeSelect: ElTreeSelect,
  Upload: ElUpload,
  JsonEditor: defineAsyncComponent(() =>
    import('@/components/JsonEditor').then((module) => module.JsonEditor)
  ),
  IconPicker: defineAsyncComponent(() =>
    import('@/components/IconPicker').then((module) => module.IconPicker)
  ),
  IAgree: IAgree
}

export { componentMap }
