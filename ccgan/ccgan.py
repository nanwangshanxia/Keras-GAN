from __future__ import print_function

from keras.datasets import cifar10
from keras.layers import Input, Dense, Reshape, Flatten, Dropout, multiply, GaussianNoise
from keras.layers import BatchNormalization, Activation, Embedding, ZeroPadding2D
from keras.layers import MaxPooling2D
from keras.layers.advanced_activations import LeakyReLU
from keras.layers.convolutional import UpSampling2D, Conv2D
from keras.models import Sequential, Model
from keras.optimizers import Adam
from keras import losses
from keras.utils import to_categorical
import keras.backend as K

import matplotlib.pyplot as plt

import numpy as np

class CCGAN():
    def __init__(self):
        self.img_rows = 32 
        self.img_cols = 32
        self.mask_height = 10
        self.mask_width = 10
        self.channels = 3
        self.num_classes = 2
        self.img_shape = (self.img_rows, self.img_cols, self.channels)

        optimizer = Adam(0.0002, 0.5)

        # Build and compile the discriminator
        self.discriminator = self.build_discriminator()
        self.discriminator.compile(loss=['binary_crossentropy', 'categorical_crossentropy'], 
            loss_weights=[0.5, 0.5],
            optimizer=optimizer,
            metrics=['accuracy'])

        # Build and compile the generator
        self.generator = self.build_generator()
        self.generator.compile(loss=['binary_crossentropy'], 
            optimizer=optimizer)

        # The generator takes noise as input and generates imgs
        masked_img = Input(shape=self.img_shape)
        gen_img = self.generator(masked_img)

        # For the combined model we will only train the generator
        self.discriminator.trainable = False

        # The valid takes generated images as input and determines validity
        valid, _ = self.discriminator(gen_img)

        # The combined model  (stacked generator and discriminator) takes
        # masked_img as input => generates images => determines validity 
        self.combined = Model(masked_img , [gen_img, valid])
        self.combined.compile(loss=['mse', 'binary_crossentropy'],
            loss_weights=[0.999, 0.001],
            optimizer=optimizer)


    def build_generator(self):

        
        model = Sequential()

        # Encoder
        model.add(Conv2D(64, kernel_size=4, strides=2, input_shape=self.img_shape, padding="same"))
        model.add(Activation('relu'))
        model.add(Conv2D(128, kernel_size=4, strides=2, padding="same"))
        model.add(Activation('relu'))
        model.add(Conv2D(256, kernel_size=4, strides=2, padding="same"))
        model.add(Activation('relu'))

        # Decoder
        model.add(UpSampling2D())
        model.add(Conv2D(128, kernel_size=4, padding="same"))
        model.add(Activation('relu'))
        model.add(UpSampling2D())
        model.add(Conv2D(64, kernel_size=4, padding="same"))
        model.add(Activation('relu'))
        model.add(UpSampling2D())
        model.add(Conv2D(self.channels, kernel_size=4, padding="same"))
        model.add(Activation('tanh'))

        model.summary()

        masked_img = Input(shape=self.img_shape)
        img = model(masked_img)

        return Model(masked_img, img)

    def build_discriminator(self):
        
        model = Sequential()

        model.add(Conv2D(32, kernel_size=3, input_shape=self.img_shape, padding="same"))
        model.add(Activation('relu'))

        model.add(MaxPooling2D())

        model.add(Conv2D(64, kernel_size=3, padding="same"))
        model.add(Activation('relu'))

        model.add(MaxPooling2D())

        model.add(Conv2D(128, kernel_size=3, padding="same"))
        model.add(Activation('relu'))
        model.add(Conv2D(128, kernel_size=3, padding="same"))
        model.add(Activation('relu'))

        model.add(MaxPooling2D())

        model.add(Conv2D(256, kernel_size=3, padding="same"))
        model.add(Activation('relu'))
        model.add(Conv2D(256, kernel_size=3, padding="same"))
        model.add(Activation('relu'))
        
        model.add(MaxPooling2D())

        model.add(Flatten())

        model.summary()

        img = Input(shape=self.img_shape)
        features = model(img)

        valid = Dense(1, activation="sigmoid")(features)
        label = Dense(self.num_classes+1, activation="softmax")(features)

        return Model(img, [valid, label])

    def mask_randomly(self, imgs):
        y1 = np.random.randint(0, self.img_rows - self.mask_height, imgs.shape[0])
        y2 = y1 + self.mask_height
        x1 = np.random.randint(0, self.img_rows - self.mask_width, imgs.shape[0])
        x2 = x1 + self.mask_width

        masked_imgs = np.empty_like(imgs)
        for i, img in enumerate(imgs):
            masked_img = img.copy()
            _y1, _y2, _x1, _x2 = y1[i], y2[i], x1[i], x2[i], 
            masked_img[_y1:_y2, _x1:_x2, :] = 0
            masked_imgs[i] = masked_img

        return masked_imgs



    def train(self, epochs, batch_size=128, save_interval=50):

        # Load the dataset

        (X_train, y_train), (X_test, y_test) = cifar10.load_data()

        X_train = np.vstack((X_train, X_test))
        y_train = np.vstack((y_train, y_test))

        # Extract dogs and cats
        X_cats = X_train[(y_train == 3).flatten()]
        y_cats = y_train[y_train == 3]
        X_dogs = X_train[(y_train == 5).flatten()]
        y_dogs = y_train[y_train == 5]
        X_train = np.vstack((X_cats, X_dogs))
        y_train = np.vstack((y_cats, y_dogs))

        # Change labels to 0 and 1
        y_train[y_train == 3] = 0
        y_train[y_train == 5] = 1

        # Rescale -1 to 1
        X_train = X_train / 255
        X_train = 2 * X_train - 1
        y_train = y_train.reshape(-1, 1)

        half_batch = int(batch_size / 2)

        # Class weights:
        # To balance the difference in occurences of digit class labels. 
        # 50% of labels that the discriminator trains on are 'fake'.
        # Weight = 1 / frequency
        cw1 = {0: 1, 1: 1}
        cw2 = {i: self.num_classes / half_batch for i in range(self.num_classes)}
        cw2[self.num_classes] = 1 / half_batch
        class_weights = [cw1, cw2]

        for epoch in range(epochs):


            # ---------------------
            #  Train Discriminator
            # ---------------------

            # Select a random half batch of images
            idx = np.random.randint(0, X_train.shape[0], half_batch)
            imgs = X_train[idx]
            labels = y_train[idx]

            masked_imgs = self.mask_randomly(imgs)
            
            # Generate a half batch of new images
            gen_imgs = self.generator.predict(masked_imgs)

            valid = np.ones((half_batch, 1))
            fake = np.zeros((half_batch, 1))

            labels = to_categorical(labels, num_classes=self.num_classes+1)
            fake_labels = to_categorical(np.full((half_batch, 1), self.num_classes), num_classes=self.num_classes+1)

            # Train the discriminator
            d_loss_real = self.discriminator.train_on_batch(imgs, [valid, labels], class_weight=class_weights)
            d_loss_fake = self.discriminator.train_on_batch(gen_imgs, [fake, fake_labels], class_weight=class_weights)
            d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)


            # ---------------------
            #  Train Generator
            # ---------------------

            # Select a random half batch of images
            idx = np.random.randint(0, X_train.shape[0], batch_size)
            imgs = X_train[idx]
            
            masked_imgs = self.mask_randomly(imgs)

            # Generator wants the discriminator to label the generated images as valid
            valid = np.ones((batch_size, 1))
            
            # Train the generator
            g_loss = self.combined.train_on_batch(masked_imgs, [imgs, valid])

            # Plot the progress
            print ("%d [D loss: %f, acc: %.2f%%, op_acc: %.2f%%] [G loss: %f, mse: %f]" % (epoch, d_loss[0], 100*d_loss[3], 100*d_loss[4], g_loss[0], g_loss[1]))

            # If at save interval => save generated image samples
            if epoch % save_interval == 0:
                # Select a random half batch of images
                idx = np.random.randint(0, X_train.shape[0], 6)
                imgs = X_train[idx]
                self.save_imgs(epoch, imgs)
                self.save_model()

    def save_imgs(self, epoch, imgs):
        r, c = 3, 6
        
        masked_imgs = self.mask_randomly(imgs)
        gen_imgs = self.generator.predict(masked_imgs)

        imgs = 0.5 * imgs + 0.5
        masked_imgs = 0.5 * masked_imgs + 0.5
        gen_imgs = 0.5 * gen_imgs + 0.5

        fig, axs = plt.subplots(r, c)
        for i in range(c):
            axs[0,i].imshow(imgs[i, :,:])
            axs[0,i].axis('off')
            axs[1,i].imshow(masked_imgs[i, :,:])
            axs[1,i].axis('off')
            axs[2,i].imshow(gen_imgs[i, :,:])
            axs[2,i].axis('off')
        fig.savefig("ccgan/images/cifar_%d.png" % epoch)
        plt.close()

    def save_model(self):

        def save(model, model_name):
            model_path = "ccgan/saved_model/%s.json" % model_name
            weights_path = "ccgan/saved_model/%s_weights.hdf5" % model_name
            options = {"file_arch": model_path, 
                        "file_weight": weights_path}
            json_string = model.to_json()
            open(options['file_arch'], 'w').write(json_string)
            model.save_weights(options['file_weight'])

        save(self.generator, "ccgan_generator")
        save(self.discriminator, "ccgan_discriminator")


if __name__ == '__main__':
    ccgan = CCGAN()
    ccgan.train(epochs=20000, batch_size=64, save_interval=50)





