// SettingsScreen.tsx
import React, {useContext} from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {Picker} from '@react-native-picker/picker';
import {ModelContext} from '../ModelContext';

export default function SettingsScreen() {
  const {
    textModel, setTextModel,
    imageModel, setImageModel,
    whisperModel, setWhisperModel
  } = useContext(ModelContext);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Settings</Text>

      {/* TEXT MODEL PICKER */}
      <Text style={styles.label}>Select Text Model:</Text>
      <Picker
        selectedValue={textModel}
        onValueChange={setTextModel}
        style={{ color: 'black', backgroundColor: 'white' }}
        itemStyle={{ color: 'black' }}
      >
        {/* Replace or add any text-based models you want */}
        <Picker.Item label="GPT-3.5 Turbo"        value="gpt-3.5-turbo" />
        <Picker.Item label="GPT-3.5 Turbo (16k)"  value="gpt-3.5-turbo-16k" />
        <Picker.Item label="GPT-4"               value="gpt-4" />
        <Picker.Item label="GPT-4 (0613)"        value="gpt-4-0613" />
        {/* or add more if needed */}
      </Picker>

      {/* IMAGE MODEL PICKER */}
      <Text style={styles.label}>Select Image Model:</Text>
      <Picker
        selectedValue={imageModel}
        onValueChange={setImageModel}
        style={{ color: 'black', backgroundColor: 'white' }}
        itemStyle={{ color: 'black' }}
      >
        {/* Replace with whatever 'Vision' models you have */}
        <Picker.Item label="GPT-4o" value="gpt-4o" />
        <Picker.Item label="GPT-4o-mini" value="gpt-4o-mini" />
      </Picker>

      {/* WHISPER MODEL PICKER */}
      <Text style={styles.label}>Select Whisper Model:</Text>
      <Picker
        selectedValue={whisperModel}
        onValueChange={setWhisperModel}
        style={{ color: 'black', backgroundColor: 'white' }}
        itemStyle={{ color: 'black' }}
      >
        <Picker.Item label="tiny" value="tiny" />
        <Picker.Item label="base" value="base" />
        <Picker.Item label="small" value="small" />
        <Picker.Item label="medium" value="medium" />
        <Picker.Item label="large" value="large" />
      </Picker>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, marginTop: 40, backgroundColor: '#fff' },
  title: { fontSize: 20, marginBottom: 20, color: 'black' },
  label: { marginTop: 20, marginBottom: 5, color: 'black' },
  picker: { height: 50, width: 220 },
});
