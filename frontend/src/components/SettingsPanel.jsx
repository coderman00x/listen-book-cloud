import React, { useEffect, useState } from 'react';
import {
  Box,
  Button,
  Drawer,
  FormControl,
  InputLabel,
  ListSubheader,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { useApp } from '../App.jsx';

// 设置面板（抽屉）：预设默认音色与默认语速，保存后新导入书籍套用。
// 语速作用于「生成阶段」（写入 mp3），与播放阶段倍速区分（见 SET-001 / SPD-001）。
// v2.0：默认音色下拉按 gender 分组（女声 / 男声 / 其他），让男声一眼可见；
// 缺 gender 字段时按名称含「男声」/「女声」优雅回退，其余归入「其他」。
export default function SettingsPanel({ open, onClose }) {
  const { settings, voices, saveSettings, notify } = useApp();
  const [voice, setVoice] = useState(settings.default_voice);
  const [rate, setRate] = useState(settings.default_rate);

  // 每次打开时同步最新值
  useEffect(() => {
    if (open) {
      setVoice(settings.default_voice);
      setRate(settings.default_rate);
    }
  }, [open, settings]);

  // 仅改变下拉的分组展示；value 仍是 v.id，保存逻辑与其它 UI 完全不动。
  const voiceItems = React.useMemo(() => {
    const groups = { female: [], male: [], other: [] };
    (voices || []).forEach((v) => {
      const name = String(v.name || '');
      let gender = v.gender;
      if (gender !== 'female' && gender !== 'male') {
        if (name.includes('男声')) gender = 'male';
        else if (name.includes('女声')) gender = 'female';
        else gender = 'other';
      }
      groups[gender].push(v);
    });
    const renderGroup = (label, items) => {
      if (!items.length) return [];
      return [
        <ListSubheader key={`group-${label}`}>{label}</ListSubheader>,
        ...items.map((v) => (
          <MenuItem key={v.id} value={v.id}>
            {v.name}
          </MenuItem>
        )),
      ];
    };
    return [
      ...renderGroup('女声', groups.female),
      ...renderGroup('男声', groups.male),
      ...renderGroup('其他', groups.other),
    ];
  }, [voices]);

  const handleSave = async () => {
    try {
      await saveSettings({ default_voice: voice, default_rate: rate });
      onClose();
    } catch (e) {
      notify(e.message, 'error');
    }
  };

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: 320, p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          默认设置
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block">
          新导入的书籍将套用以下音色与语速（语速作用于生成阶段的 mp3）。
        </Typography>

        <FormControl fullWidth sx={{ mt: 2 }}>
          <InputLabel id="voice-label">默认音色</InputLabel>
          <Select
            labelId="voice-label"
            label="默认音色"
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
          >
            {voiceItems}
          </Select>
        </FormControl>

        <TextField
          fullWidth
          sx={{ mt: 2 }}
          label="默认语速"
          value={rate}
          helperText="如 +0% / +20% / -30%"
          onChange={(e) => setRate(e.target.value)}
        />

        <Stack direction="row" spacing={1} sx={{ mt: 3, justifyContent: 'flex-end' }}>
          <Button onClick={onClose}>取消</Button>
          <Button variant="contained" onClick={handleSave}>
            保存
          </Button>
        </Stack>
      </Box>
    </Drawer>
  );
}
