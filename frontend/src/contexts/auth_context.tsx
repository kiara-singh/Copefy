import React, { createContext, useContext, useEffect, useState, useRef } from "react";
import { Session, User } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase_client";

export interface Profile {
  id: string;
  created_at: string;
  updated_at: string;
  current_triage_tier: number;
  subscription_tier: string;
  consent: boolean;
  legal_consent: any;
  preferred_name: string | null;
  communication_style: string | null;
  wellness_goal: string | null;
  onboarding_complete: boolean;
}

interface AuthContextType {
  user: User | null;
  session: Session | null;
  profile: Profile | null;
  loading: boolean;
  updateProfile: (updates: Partial<Omit<Profile, "id" | "created_at" | "updated_at">>) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const last_user_id_ref = useRef<string | null>(null);

  const fetchProfile = async (userId: string) => {
    try {
      const { data, error } = await supabase
        .from("profiles")
        .select("*")
        .eq("id", userId)
        .single();

      if (error) {
        console.error("Failed to fetch profile:", error.message);
        setProfile(null);
      } else {
        setProfile(data as Profile);
      }
    } catch (err) {
      console.error("Error in fetchProfile:", err);
      setProfile(null);
    }
  };

  const updateProfile = async (updates: Partial<Omit<Profile, "id" | "created_at" | "updated_at">>) => {
    if (!user) {
      throw new Error("No authenticated user to update profile for");
    }

    const { data, error } = await supabase
      .from("profiles")
      .update(updates)
      .eq("id", user.id)
      .select()
      .single();

    if (error) {
      console.error("Failed to update profile:", error.message);
      throw error;
    }

    if (data) {
      setProfile(data as Profile);
    }
  };

  useEffect(() => {
    // Restore session on startup
    const get_initial_session = async () => {
      try {
        const {
          data: { session: initial_session },
        } = await supabase.auth.getSession();
        setSession(initial_session);
        const current_user = initial_session?.user ?? null;
        last_user_id_ref.current = current_user?.id ?? null;
        setUser(current_user);
        if (current_user) {
          await fetchProfile(current_user.id);
        } else {
          setProfile(null);
        }
      } catch (error) {
        console.error("Failed to restore supabase session on startup:", error);
      } finally {
        setLoading(false);
      }
    };

    get_initial_session();

    // Subscribe to auth state changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (_event, current_session) => {
      setSession(current_session);
      const current_user = current_session?.user ?? null;

      // Only load profile if user actually changed (e.g. login, logout, new user session)
      if (current_user?.id !== last_user_id_ref.current) {
        last_user_id_ref.current = current_user?.id ?? null;
        setUser(current_user);

        if (current_user) {
          setLoading(true);
          await fetchProfile(current_user.id);
        } else {
          setProfile(null);
        }
        setLoading(false);
      }
    });

    // Cleanup subscription
    return () => {
      subscription.unsubscribe();
    };
  }, []);

  return (
    <AuthContext.Provider value={{ user, session, profile, loading, updateProfile }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
