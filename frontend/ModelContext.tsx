// ModelContext.tsx
import React, {createContext, useState} from 'react';

export const ModelContext = createContext({
  textModel: 'gpt-3.5-turbo',
  setTextModel: (model: string) => {},
  imageModel: 'gpt-4o-mini',
  setImageModel: (model: string) => {},
  whisperModel: 'base',
  setWhisperModel: (wm: string) => {},
});

export const ModelProvider = ({children}: any) => {
  const [textModel, setTextModel] = useState('gpt-3.5-turbo');
  const [imageModel, setImageModel] = useState('gpt-4o-mini');
  const [whisperModel, setWhisperModel] = useState('base');

  return (
    <ModelContext.Provider
      value={{
        textModel,
        setTextModel,
        imageModel,
        setImageModel,
        whisperModel,
        setWhisperModel,
      }}
    >
      {children}
    </ModelContext.Provider>
  );
};
