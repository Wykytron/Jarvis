import React, {useState, useEffect, useContext} from 'react';
import {
  View,
  PermissionsAndroid,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  FlatList,
  Text,
  Image,
} from 'react-native';
import {NavigationContainer} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import MaterialCommunityIcons from 'react-native-vector-icons/MaterialCommunityIcons';
import Tts from 'react-native-tts';
import AudioRecord from 'react-native-audio-record';
import axios from 'axios';

import {
  launchCamera,
  launchImageLibrary,
  Asset,
} from 'react-native-image-picker';

import SettingsScreen from './screens/SettingsScreen';
import {ModelProvider, ModelContext} from './ModelContext';

const BACKEND_TRANSCRIBE_URL = 'http://192.168.0.189:8000/api/transcribe';
const BACKEND_CHAT_URL = 'http://192.168.0.189:8000/api/chat';

const Stack = createNativeStackNavigator();

function HomeScreen({navigation}: any) {
  const { textModel, imageModel, whisperModel } = useContext(ModelContext);

  const [messages, setMessages] = useState<any[]>([]);
  const [recording, setRecording] = useState(false);
  const [audioFile, setAudioFile] = useState<string>('');
  const [speakerOn, setSpeakerOn] = useState<boolean>(false);

  // The user's typed text
  const [textMessage, setTextMessage] = useState('');
  // If we want text+image in the same message, we store the selected image until we click "Send"
  const [selectedImageUri, setSelectedImageUri] = useState<string | null>(null);

  useEffect(() => {
    MaterialCommunityIcons.loadFont();
  }, []);

  //=== PERMISSIONS
  const requestPermissions = async () => {
    try {
      await PermissionsAndroid.requestMultiple([
        PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
        PermissionsAndroid.PERMISSIONS.WRITE_EXTERNAL_STORAGE,
      ]);
    } catch (err) {
      console.warn(err);
    }
  };

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

  //=== RECORDING
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

    // Transcribe
    try {
      const formData = new FormData();
      formData.append('whisper_model', whisperModel);
      formData.append('file', {
        uri: 'file://' + filePath,
        name: 'audio.wav',
        type: 'audio/wav',
      });

      const resp = await axios.post(BACKEND_TRANSCRIBE_URL, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const transcript = resp.data.transcript || '';
      setTextMessage(transcript);
    } catch (error) {
      console.log('Transcribe error:', error);
    }
  };

  //=== SPEAKER TOGGLE
  const toggleSpeaker = () => {
    setSpeakerOn(prev => !prev);
  };

  //=== CHOOSE IMAGE (Camera or Gallery)
  const handleTakePhoto = async () => {
    const hasCam = await requestCameraPermission();
    if (!hasCam) {
      console.log('Camera permission denied');
      return;
    }
    const result = await launchCamera({mediaType: 'photo'});
    if (!result.didCancel && !result.errorCode && result.assets?.length) {
      const asset: Asset = result.assets[0];
      if (asset.uri) {
        // Store the image in state, do NOT send immediately
        setSelectedImageUri(asset.uri);
      }
    }
  };

  const handleChooseFromGallery = async () => {
    const result = await launchImageLibrary({mediaType: 'photo'});
    if (!result.didCancel && !result.errorCode && result.assets?.length) {
      const asset: Asset = result.assets[0];
      if (asset.uri) {
        setSelectedImageUri(asset.uri);
      }
    }
  };

  //=== SEND MESSAGE (Text + optional Image)
  const sendMessage = async () => {
    // If both text and image are empty, do nothing
    if (!textMessage.trim() && !selectedImageUri) {
      return;
    }

    // Show user message in the chat (could be text only, image only, or both).
    // We'll unify it as a single "user" message in the UI. For simplicity, you can:
    //  - Display text + image in the same bubble
    //  OR
    //  - Display them as separate items (like before).
    // Here, let's do a single bubble if there's text, and an image below if there's an image:
    const userMsgId = Date.now().toString();

    if (textMessage.trim()) {
      setMessages(prev => [
        ...prev,
        {
          id: userMsgId + '-text',
          role: 'user',
          type: 'text',
          content: textMessage.trim(),
        },
      ]);
    }
    if (selectedImageUri) {
      setMessages(prev => [
        ...prev,
        {
          id: userMsgId + '-img',
          role: 'user',
          type: 'image',
          content: selectedImageUri,
        },
      ]);
    }

    // Decide which GPT model to use. If there's an image, we must use the imageModel
    const chosenModel = selectedImageUri ? imageModel : textModel;

    // Build the form data
    const formData = new FormData();
    formData.append('model', chosenModel);
    formData.append('message', textMessage.trim() || '');

    if (selectedImageUri) {
      formData.append('file', {
        uri: selectedImageUri,
        type: 'image/jpeg',
        name: 'photo.jpg',
      });
    }

    // Clear local states (to reset input)
    setTextMessage('');
    setSelectedImageUri(null);

    try {
      const resp = await axios.post(BACKEND_CHAT_URL, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const reply = resp.data.response || '(No response)';

      if (speakerOn) {
        Tts.speak(reply);
      }

      const assistantMsg = {
        id: `${Date.now()}-app`,
        role: 'app',
        type: 'text',
        content: reply,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (error) {
      console.log('Error sending message:', error);
      // Optionally show an error message in the chat
      setMessages(prev => [
        ...prev,
        {
          id: `${Date.now()}-err`,
          role: 'app',
          type: 'text',
          content: 'Error calling the model.',
        },
      ]);
    }
  };

  //=== RENDER MESSAGES
  const renderMessage = ({item}: {item: any}) => {
    const isUser = item.role === 'user';
    const bubbleStyle = isUser
      ? [styles.bubble, styles.userBubble]
      : [styles.bubble, styles.appBubble];
    const textStyle = isUser ? styles.userText : styles.appText;

    if (item.type === 'image') {
      return (
        <View style={bubbleStyle}>
          <Image source={{uri: item.content}} style={styles.imageBubble} />
        </View>
      );
    }
    return (
      <View style={bubbleStyle}>
        <Text style={textStyle}>{item.content}</Text>
      </View>
    );
  };

  return (
    <View style={styles.container}>
      <FlatList
        data={messages}
        renderItem={renderMessage}
        keyExtractor={item => item.id}
        contentContainerStyle={{paddingTop: 10, paddingBottom: 80}}
        style={styles.chatList}
      />

      <View style={styles.buttonsRow}>
        <TouchableOpacity style={styles.iconButton} onPress={() => navigation.navigate('Settings')}>
          <MaterialCommunityIcons name="cog-outline" size={30} color="#fff" />
        </TouchableOpacity>

        <TouchableOpacity style={styles.iconButton} onPress={handleTakePhoto}>
          <MaterialCommunityIcons name="camera" size={30} color="#fff" />
        </TouchableOpacity>

        <TouchableOpacity style={styles.iconButton} onPress={handleChooseFromGallery}>
          <MaterialCommunityIcons name="folder-image" size={30} color="#fff" />
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.iconButton, {backgroundColor: speakerOn ? 'green' : 'red'}]}
          onPress={toggleSpeaker}
        >
          <MaterialCommunityIcons name="volume-high" size={30} color="#fff" />
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.iconButton, recording && styles.recording]}
          onPress={recording ? stopRecording : startRecording}
        >
          <MaterialCommunityIcons name="microphone" size={30} color="#fff" />
        </TouchableOpacity>
      </View>

      {/* If an image is selected, show a small preview before sending */}
      {selectedImageUri && (
        <View style={styles.selectedImagePreview}>
          <Image source={{uri: selectedImageUri}} style={{width: 60, height: 60, borderRadius: 8}} />
          <Text style={{marginLeft: 10, color: 'gray'}}>Image attached</Text>
        </View>
      )}

      <View style={styles.inputRow}>
        <TextInput
          style={styles.textInput}
          placeholder="Type or speak message..."
          value={textMessage}
          onChangeText={setTextMessage}
        />
        <TouchableOpacity style={styles.sendButton} onPress={sendMessage}>
          <MaterialCommunityIcons name="send" size={24} color="#fff" />
        </TouchableOpacity>
      </View>
    </View>
  );
}

function App() {
  return (
    <ModelProvider>
      <NavigationContainer>
        <Stack.Navigator>
          <Stack.Screen
            name="Home"
            component={HomeScreen}
            options={{headerShown: false}}
          />
          <Stack.Screen name="Settings" component={SettingsScreen} />
        </Stack.Navigator>
      </NavigationContainer>
    </ModelProvider>
  );
}

export default App;

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
  buttonsRow: {
    flexDirection: 'row',
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
  selectedImagePreview: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 8,
    marginBottom: 5,
  },
});
