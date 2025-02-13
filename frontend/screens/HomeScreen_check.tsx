import React, { useState, useEffect, useContext } from 'react';
import {
  View,
  PermissionsAndroid,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  FlatList,
  Text,
  Image,
  Modal,
} from 'react-native';
import MaterialCommunityIcons from 'react-native-vector-icons/MaterialCommunityIcons';
import Tts from 'react-native-tts';
import AudioRecord from 'react-native-audio-record';
import axios from 'axios';
import {
  launchCamera,
  launchImageLibrary,
  Asset,
} from 'react-native-image-picker';
import DocumentPicker, { types } from 'react-native-document-picker';

import { ModelContext } from '../ModelContext';

// Adjust these if needed:
const BACKEND_URL = 'http://192.168.0.189:8000';
const BACKEND_TRANSCRIBE_URL = `${BACKEND_URL}/api/transcribe`;
const BACKEND_CHAT_URL = `${BACKEND_URL}/api/chat`;
const BACKEND_INGEST_URL = `${BACKEND_URL}/api/ingest`;

function HomeScreen({ navigation }: any) {
  const { textModel, imageModel, whisperModel } = useContext(ModelContext);

  // Chat states
  const [messages, setMessages] = useState<any[]>([]);
  const [recording, setRecording] = useState(false);
  const [audioFile, setAudioFile] = useState<string>('');
  const [speakerOn, setSpeakerOn] = useState<boolean>(false);
  const [textMessage, setTextMessage] = useState('');

  // File / image selection
  const [selectedImageUri, setSelectedImageUri] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<{
    uri: string;
    name: string;
    type: string;
  } | null>(null);

  //========================================
  // NEW: Manage tasks & errors for status
  //========================================
  const [tasksInProgress, setTasksInProgress] = useState<string[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [showStatusPopup, setShowStatusPopup] = useState(false);

  function addTask(label: string) {
    setTasksInProgress((prev) => [...prev, label]);
    console.log(`>>> addTask: ${label}`);
  }
  function removeTask(label: string) {
    setTasksInProgress((prev) => prev.filter((t) => t !== label));
    console.log(`>>> removeTask: ${label}`);
  }
  function addError(msg: string) {
    setErrors((prev) => [...prev, msg]);
    console.log(`>>> addError: ${msg}`);
  }
  function clearErrors() {
    setErrors([]);
  }
  function toggleStatusPopup() {
    setShowStatusPopup(!showStatusPopup);
  }

  // Decide how the status button looks
  function getStatusButtonStyle() {
    if (errors.length > 0) {
      // errors => red
      return { backgroundColor: 'red' };
    } else if (tasksInProgress.length > 0) {
      // tasks => blue
      return { backgroundColor: 'blue' };
    }
    // default
    return { backgroundColor: '#555' };
  }
  function getStatusButtonIconName() {
    if (errors.length > 0) {
      return 'alert-circle';
    } else if (tasksInProgress.length > 0) {
      return 'progress-clock';
    }
    return 'information-outline';
  }

  //========================================
  // Single Attach Menu Toggle
  //========================================
  const [showAttachMenu, setShowAttachMenu] = useState(false);
  function toggleAttachMenu() {
    setShowAttachMenu(!showAttachMenu);
  }

  //========================================
  // Effects, Permissions, etc.
  //========================================
  useEffect(() => {
    MaterialCommunityIcons.loadFont();
  }, []);

  async function requestPermissions() {
    try {
      await PermissionsAndroid.requestMultiple([
        PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
        PermissionsAndroid.PERMISSIONS.WRITE_EXTERNAL_STORAGE,
      ]);
    } catch (err) {
      console.warn(err);
    }
  }

  async function requestCameraPermission() {
    const granted = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.CAMERA,
      {
        title: 'Camera Permission',
        message: 'App needs camera access',
        buttonNeutral: 'Ask Me Later',
        buttonNegative: 'Cancel',
        buttonPositive: 'OK',
      },
    );
    return granted === PermissionsAndroid.RESULTS.GRANTED;
  }

  //========================================
  // Audio Recording
  //========================================
  const startRecording = async () => {
    await requestPermissions();
    AudioRecord.init({
      sampleRate: 16000,
      channels: 1,
      bitsPerSample: 16,
    });
    AudioRecord.start();
    setRecording(true);
  };

  const stopRecording = async () => {
    const filePath = await AudioRecord.stop();
    setRecording(false);
    setAudioFile(filePath);

    addTask('Transcription');
    try {
      const formData = new FormData();
      formData.append('whisper_model', whisperModel);
      formData.append('file', {
        uri: 'file://' + filePath,
        name: 'audio.wav',
        type: 'audio/wav',
      } as any);

      const resp = await axios.post(BACKEND_TRANSCRIBE_URL, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      removeTask('Transcription');
      const transcript = resp.data.transcript || '';
      setTextMessage(transcript);
    } catch (error: any) {
      removeTask('Transcription');
      const msg = error?.message || '(Network error)';
      addError(`Transcription failed: ${msg}`);
      console.log('Error transcribing audio:', error);
    }
  };

  //========================================
  // Camera / Gallery
  //========================================
  const handleTakePhoto = async () => {
    toggleAttachMenu();
    const hasCam = await requestCameraPermission();
    if (!hasCam) {
      console.log('Camera permission denied');
      return;
    }
    const result = await launchCamera({ mediaType: 'photo' });
    if (!result.didCancel && !result.errorCode && result.assets?.length) {
      const asset: Asset = result.assets[0];
      if (asset.uri) {
        setSelectedImageUri(asset.uri);
      }
    }
  };

  const handleChooseFromGallery = async () => {
    toggleAttachMenu();
    const result = await launchImageLibrary({ mediaType: 'photo' });
    if (!result.didCancel && !result.errorCode && result.assets?.length) {
      const asset: Asset = result.assets[0];
      if (asset.uri) {
        setSelectedImageUri(asset.uri);
      }
    }
  };

  //========================================
  // Doc Picker
  //========================================
  const handlePickDoc = async () => {
    toggleAttachMenu();
    try {
      const res = await DocumentPicker.pickSingle({
        presentationStyle: 'fullScreen',
        type: [types.pdf, types.docx, types.plainText],
      });
      console.log('Picked doc:', res);
      setSelectedDoc({
        uri: res.uri,
        name: res.name ?? 'unnamed',
        type: res.type ?? 'application/octet-stream',
      });
    } catch (err) {
      if (DocumentPicker.isCancel(err)) {
        console.log('User canceled doc picker');
      } else {
        console.log('Document pick error:', err);
      }
    }
  };

  //========================================
  // Send (Doc / Image / Text)
  //========================================
  const sendMessage = async () => {
    // 1) Doc ingest
    if (selectedDoc) {
      addTask('Doc Ingestion');
      try {
        const formData = new FormData();
        formData.append('file', {
          uri: selectedDoc.uri,
          type: selectedDoc.type,
          name: selectedDoc.name,
        } as any);
        formData.append('description', textMessage);

        const resp = await axios.post(BACKEND_INGEST_URL, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        console.log('Doc ingestion resp:', resp.data);

        removeTask('Doc Ingestion');
        setMessages((prev) => [
          ...prev,
          {
            id: `doc-ingest-${Date.now()}`,
            role: 'app',
            type: 'text',
            content: `Ingested doc_id=${resp.data.doc_id}, desc="${resp.data.description}"`,
          },
        ]);
      } catch (error: any) {
        removeTask('Doc Ingestion');
        const msg = error?.message || '(Network error)';
        addError(`Doc ingestion failed: ${msg}`);
        console.log('Error ingesting doc:', error);
      }
      setSelectedDoc(null);
      setTextMessage('');
      return;
    }

    // 2) Image
    if (selectedImageUri) {
      const trimmed = textMessage.trim();
      if (trimmed) {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}-text`,
            role: 'user',
            type: 'text',
            content: trimmed,
          },
          {
            id: `${Date.now()}-img`,
            role: 'user',
            type: 'image',
            content: selectedImageUri,
          },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: `${Date.now()}-img`,
            role: 'user',
            type: 'image',
            content: selectedImageUri,
          },
        ]);
      }

      addTask('Image Upload');
      const formData = new FormData();
      formData.append('model', imageModel);
      formData.append('message', trimmed);
      formData.append('file', {
        uri: selectedImageUri,
        type: 'image/jpeg',
        name: 'photo.jpg',
      } as any);

      setTextMessage('');
      setSelectedImageUri(null);

      try {
        const resp = await axios.post(BACKEND_CHAT_URL, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        removeTask('Image Upload');

        const reply = resp.data.response || '(No response)';
        if (speakerOn) {
          Tts.speak(reply);
        }
        setMessages((prev) => [
          ...prev,
          {
            id: `app-${Date.now()}`,
            role: 'app',
            type: 'text',
            content: reply,
          },
        ]);
      } catch (error: any) {
        removeTask('Image Upload');
        const msg = error?.message || '(Network error)';
        addError(`Image upload failed: ${msg}`);
        console.log('Error sending image:', error);
      }
      return;
    }

    // 3) Text only
    const trimmedMsg = textMessage.trim();
    if (!trimmedMsg) return;

    setMessages((prev) => [
      ...prev,
      {
        id: `user-msg-${Date.now()}`,
        role: 'user',
        type: 'text',
        content: trimmedMsg,
      },
    ]);

    addTask('Chat Request');
    const formData = new FormData();
    formData.append('model', textModel);
    formData.append('message', trimmedMsg);

    setTextMessage('');

    try {
      const resp = await axios.post(BACKEND_CHAT_URL, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      removeTask('Chat Request');

      const reply = resp.data.response || '(No response)';
      if (speakerOn) {
        Tts.speak(reply);
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `app-msg-${Date.now()}`,
          role: 'app',
          type: 'text',
          content: reply,
        },
      ]);
    } catch (error: any) {
      removeTask('Chat Request');
      const msg = error?.message || '(Network error)';
      addError(`Chat request failed: ${msg}`);
      console.log('Error sending message:', error);
    }
  };

  //========================================
  // Speaker Toggle
  //========================================
  const toggleSpeaker = () => {
    setSpeakerOn((prev) => !prev);
  };

  //========================================
  // Render Chat Messages
  //========================================
  const renderMessage = ({ item }: { item: any }) => {
    const isUser = item.role === 'user';
    const bubbleStyle = isUser
      ? [styles.bubble, styles.userBubble]
      : [styles.bubble, styles.appBubble];
    const textStyle = isUser ? styles.userText : styles.appText;

    if (item.type === 'image') {
      return (
        <View style={bubbleStyle}>
          <Image source={{ uri: item.content }} style={styles.imageBubble} />
        </View>
      );
    }
    return (
      <View style={bubbleStyle}>
        <Text style={textStyle}>{item.content}</Text>
      </View>
    );
  };

  //========================================
  // Main Render
  //========================================
  return (
    <View style={styles.container}>
      {/* Chat List */}
      <FlatList
        data={messages}
        renderItem={renderMessage}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ paddingTop: 10, paddingBottom: 80 }}
        style={styles.chatList}
      />

      {/* File Previews (unchanged) */}
      {selectedDoc && (
        <View style={styles.selectedFilePreview}>
          <Text style={{ color: 'gray' }}>{`Doc attached: ${selectedDoc.name}`}</Text>
        </View>
      )}
      {selectedImageUri && (
        <View style={styles.selectedFilePreview}>
          <Image
            source={{ uri: selectedImageUri }}
            style={{ width: 60, height: 60, borderRadius: 8 }}
          />
          <Text style={{ marginLeft: 10, color: 'gray' }}>Image attached</Text>
        </View>
      )}

      {/* Bottom Buttons Row */}
      <View style={styles.buttonsRow}>
        {/* Settings */}
        <TouchableOpacity
          style={styles.iconButton}
          onPress={() => navigation.navigate('Settings')}
        >
          <MaterialCommunityIcons name="cog-outline" size={30} color="#fff" />
        </TouchableOpacity>

        {/* Single Attach Button w/ sub-menu */}
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <TouchableOpacity
            style={styles.iconButton}
            onPress={toggleAttachMenu}
          >
            <MaterialCommunityIcons name="paperclip" size={25} color="#fff" />
          </TouchableOpacity>

          {/* Sub-menu for doc/camera/gallery */}
          {showAttachMenu && (
            <View style={styles.attachSubMenu}>
              <TouchableOpacity style={styles.subButton} onPress={handlePickDoc}>
                <MaterialCommunityIcons name="file-document" size={24} color="#fff" />
              </TouchableOpacity>
              <TouchableOpacity style={styles.subButton} onPress={handleTakePhoto}>
                <MaterialCommunityIcons name="camera" size={24} color="#fff" />
              </TouchableOpacity>
              <TouchableOpacity style={styles.subButton} onPress={handleChooseFromGallery}>
                <MaterialCommunityIcons name="folder-image" size={24} color="#fff" />
              </TouchableOpacity>
            </View>
          )}
        </View>

        {/* Status Button */}
        <TouchableOpacity
          style={[styles.iconButton, getStatusButtonStyle()]}
          onPress={toggleStatusPopup}
        >
          <MaterialCommunityIcons
            name={getStatusButtonIconName()}
            size={30}
            color="#fff"
          />
        </TouchableOpacity>

        {/* Speaker Toggle */}
        <TouchableOpacity
          style={[
            styles.iconButton,
            { backgroundColor: speakerOn ? 'green' : 'red' },
          ]}
          onPress={toggleSpeaker}
        >
          <MaterialCommunityIcons name="volume-high" size={30} color="#fff" />
        </TouchableOpacity>

        {/* Microphone (rightmost) */}
        <TouchableOpacity
          style={[styles.iconButton, recording && styles.recording]}
          onPress={recording ? stopRecording : startRecording}
        >
          <MaterialCommunityIcons name="microphone" size={30} color="#fff" />
        </TouchableOpacity>
      </View>

      {/* Input Row */}
      <View style={styles.inputRow}>
        <TextInput
          style={styles.textInput}
          placeholder="Type your message or doc description..."
          value={textMessage}
          onChangeText={setTextMessage}
        />
        <TouchableOpacity style={styles.sendButton} onPress={sendMessage}>
          <MaterialCommunityIcons name="send" size={24} color="#fff" />
        </TouchableOpacity>
      </View>

      {/* Status Popup Modal */}
      <Modal
        visible={showStatusPopup}
        transparent
        animationType="fade"
        onRequestClose={() => setShowStatusPopup(false)}
      >
        <View style={styles.overlay}>
          <View style={styles.popup}>
            <Text style={styles.popupTitle}>Status</Text>

            <Text style={styles.popupSubTitle}>Tasks in progress:</Text>
            {tasksInProgress.length === 0 && (
              <Text style={styles.popupText}>No active tasks.</Text>
            )}
            {tasksInProgress.map((t, idx) => (
              <Text key={idx} style={styles.popupText}>
                - {t}
              </Text>
            ))}

            <Text style={[styles.popupSubTitle, { marginTop: 10 }]}>Errors:</Text>
            {errors.length === 0 && (
              <Text style={[styles.popupText]}>No errors.</Text>
            )}
            {errors.map((e, idx) => (
              <Text key={idx} style={[styles.popupText, { color: 'red' }]}>
                - {e}
              </Text>
            ))}

            {/* Close / Clear errors */}
            <View style={styles.popupButtonsRow}>
              <TouchableOpacity
                style={styles.popupButton}
                onPress={() => setShowStatusPopup(false)}
              >
                <Text style={{ color: '#fff' }}>Close</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.popupButton}
                onPress={() => clearErrors()}
              >
                <Text style={{ color: '#fff' }}>Clear Errors</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

export default HomeScreen;

//==============================================
// Styles
//==============================================
const styles = StyleSheet.create({
  container: {
    flex: 1,
    marginTop: 40,
    backgroundColor: '#f0f0f0',
  },
  chatList: {
    flex: 1,
  },
  bubble: {
    marginVertical: 4,
    marginHorizontal: 8,
    maxWidth: '70%',
    borderRadius: 12,
    padding: 8,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#007aff',
  },
  appBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#ddd',
  },
  userText: {
    color: '#fff',
  },
  appText: {
    color: '#333',
  },
  imageBubble: {
    width: 150,
    height: 150,
    borderRadius: 8,
  },

  // File/Doc preview
  selectedFilePreview: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 8,
    marginBottom: 5,
  },

  buttonsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
  },
  iconButton: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: '#555',
    justifyContent: 'center',
    alignItems: 'center',
    marginHorizontal: 5,
  },
  recording: {
    backgroundColor: 'red',
  },
  // Sub-menu for attach
  attachSubMenu: {
    flexDirection: 'row',
    marginLeft: 5,
  },
  subButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#777',
    justifyContent: 'center',
    alignItems: 'center',
    marginHorizontal: 3,
  },

  // Input row
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingBottom: 10,
  },
  textInput: {
    flex: 1,
    height: 45,
    backgroundColor: '#fff',
    borderRadius: 8,
    paddingHorizontal: 10,
  },
  sendButton: {
    width: 45,
    height: 45,
    borderRadius: 8,
    marginLeft: 8,
    backgroundColor: '#007aff',
    justifyContent: 'center',
    alignItems: 'center',
  },

  // Modal overlay
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  popup: {
    width: '80%',
    backgroundColor: '#fff',
    borderRadius: 8,
    padding: 16,
  },
  popupTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 10,
    color: '#333',
  },
  popupSubTitle: {
    fontWeight: '600',
    marginBottom: 5,
    color: '#333',
  },
  popupText: {
    color: '#333',
    marginBottom: 2,
  },
  popupButtonsRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 15,
  },
  popupButton: {
    backgroundColor: '#007aff',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginLeft: 10,
  },
});
