package com.reviewtrust.network

import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Singleton that provides the Retrofit instance with OkHttp logging.
 */
object RetrofitClient {

    // Backend URL: Points to your local PC running Uvicorn
    // If using ADB USB tunnel:  adb reverse tcp:8000 tcp:8000  → use "http://localhost:8000/"
    // Backend URL: Live Render backend
    private const val BASE_URL = "https://reviewtrust.onrender.com/"

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BODY
    }

    private val httpClient = OkHttpClient.Builder()
        .addInterceptor(loggingInterceptor)
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)   // scraping 50+ reviews takes ~30-60 s
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    val instance: ApiService by lazy {
        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(httpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
    }
}
